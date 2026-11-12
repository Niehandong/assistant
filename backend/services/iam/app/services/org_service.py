"""组织管理（5.2）：树/选择器、增删改、移动（子树重算）、停用（吊销会话）、删除。

约定：
* 所有单节点读写先 ``_get_visible``（未删除且在数据范围内，否则 404000，防止通过 ID 越权）。
* 写操作对目标行 ``SELECT ... FOR UPDATE`` 后校验 ``version``（409001），串行化并发编辑。
* 批量 UPDATE（子树 ancestors/company_id、用户 company_id）一律显式写 ``updated_at/updated_by``（见 repo）。
* 使权限上下文失效的操作（新增/移动/停用/删除）提交后递增 ``authz:epoch``。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import OrgType, RevokeReason, Status
from app.models import SysOrg
from app.repositories import org_repo, role_repo, scope, user_repo
from app.schemas.org import OrgCreate, OrgMove, OrgNode, OrgOption, OrgStatusBody, OrgUpdate
from app.services import authz_service, downstream, event_service, org_protection, session_service
from platform_common.auth.context import AuthContext
from platform_common.errors import BizError, CommonErrors
from platform_common.oplog import oplog_scope

logger = logging.getLogger(__name__)

COMPANY_UNDER_DEPT = (400110, "部门下不能创建公司")
COMPANY_PARENT_INVALID = (400111, "公司的上级只能是集团或公司")
MOVE_INTO_SELF = (400112, "不能移动到自身或下级组织之下")
GROUP_PROTECTED = org_protection.GROUP_PROTECTED
NAME_EXISTS = (409101, "同一上级下已存在同名组织")
CODE_EXISTS = (409102, "组织编码已存在")
HAS_CHILDREN = (409103, "存在下级组织，不能删除")
HAS_USERS = (409104, "组织下存在用户，不能删除")
HAS_DATASETS = (409105, "组织下存在知识库，不能删除")
HAS_COMPANY_ROLES = (409106, "存在归属该公司的角色，不能删除")


# --------------------------------------------------------------------------- 内部工具


def _not_found() -> BizError:
    return BizError(*CommonErrors.NOT_FOUND)


async def _get_visible(
    session: AsyncSession, ctx: AuthContext, org_id: int, *, for_update: bool = False, manage: bool = True
) -> SysOrg:
    """取未删除组织。完全不可见 → 404000（防止通过 ID 越权）；

    ``manage=True``（写操作与写前校验，默认）要求在管理范围内，可见但不可管理（SELF 本人组织链特例）→ 403001；
    ``manage=False`` 用于查询，按可见范围判断。
    """
    org = await org_repo.get_active(session, org_id, for_update=for_update) if org_id > 0 else None
    if org is None or not scope.org_visible(ctx, org):
        raise _not_found()
    if manage and not scope.org_manageable(ctx, org):
        raise BizError(*CommonErrors.FORBIDDEN)
    return org


def _ensure_version(org: SysOrg, version: int) -> None:
    if org.version != version:
        raise BizError(*CommonErrors.VERSION_CONFLICT)


def _ancestor_ids(org: SysOrg) -> list[int]:
    return [int(x) for x in org.ancestors.split(",") if x and int(x) != 0]


async def _bump_epoch_safely() -> None:
    """提交后立即使全部权限上下文缓存失效；Redis 异常只记日志（缓存 TTL 兜底）。"""
    try:
        await authz_service.bump_epoch()
    except Exception:
        logger.error("递增 authz:epoch 失败", exc_info=True)


async def _flush_org(session: AsyncSession) -> None:
    """flush，并发下的唯一约束冲突转换为业务错误。"""
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        msg = str(exc.orig)
        if "uq_sys_org_parent_name" in msg:
            raise BizError(*NAME_EXISTS) from exc
        if "sys_org_code_key" in msg:
            raise BizError(*CODE_EXISTS) from exc
        raise


def _check_hierarchy(org_type: str, parent: SysOrg) -> None:
    """层级规则（新增与移动共用）：公司的上级只能是集团/公司；部门的上级可以是集团/公司/部门
    （集团节点视为"集团本部"，可直接下设部门）。"""
    if org_type == OrgType.COMPANY:
        if parent.org_type == OrgType.DEPT:
            raise BizError(*COMPANY_UNDER_DEPT)
        if parent.org_type not in (OrgType.GROUP, OrgType.COMPANY):
            raise BizError(*COMPANY_PARENT_INVALID)
    elif org_type == OrgType.DEPT:
        if parent.org_type not in (OrgType.GROUP, OrgType.COMPANY, OrgType.DEPT):
            raise BizError(CommonErrors.INVALID_PARAMS[0], "部门的上级只能是集团、公司或部门")


async def _check_leader(session: AsyncSession, ctx: AuthContext, leader_user_id: int | None) -> None:
    if leader_user_id is None:
        return
    if not await user_repo.visible_user_exists(
        session, leader_user_id, scope.manage_user_filter(ctx)
    ):  # 写前校验：管理范围
        raise BizError(CommonErrors.INVALID_PARAMS[0], "负责人不存在或不在您的数据范围内")


def _snapshot(org: SysOrg) -> dict[str, Any]:
    return {
        "parent_id": org.parent_id,
        "name": org.name,
        "code": org.code,
        "org_type": org.org_type,
        "leader_user_id": org.leader_user_id,
        "sort_order": org.sort_order,
        "status": org.status,
    }


async def _effective_statuses(session: AsyncSession, orgs: Iterable[SysOrg]) -> dict[int, str]:
    """org.id → 生效状态：自身或任一祖先停用（或祖先缺失/已删除）则 disabled。"""
    orgs = list(orgs)
    known = {o.id: o for o in orgs}
    missing = {a for o in orgs for a in _ancestor_ids(o)} - known.keys()
    ancestors = await org_repo.get_by_ids(session, missing)
    result: dict[int, str] = {}
    for o in orgs:
        disabled = o.status != Status.ENABLED
        for a in _ancestor_ids(o):
            anc = known.get(a) or ancestors.get(a)
            if anc is None or anc.is_deleted or anc.status != Status.ENABLED:
                disabled = True
                break
        result[o.id] = Status.DISABLED if disabled else Status.ENABLED
    return result


async def _leader_names(session: AsyncSession, orgs: Iterable[SysOrg]) -> dict[int, str]:
    ids = {o.leader_user_id for o in orgs if o.leader_user_id}
    users = await user_repo.get_by_ids(session, ids)
    return {uid: u.name for uid, u in users.items() if not u.is_deleted}


async def _to_nodes(
    session: AsyncSession,
    orgs: list[SysOrg],
    protection: org_protection.OrgProtection | None = None,
    ctx: AuthContext | None = None,
) -> dict[int, OrgNode]:
    eff = await _effective_statuses(session, orgs)
    leaders = await _leader_names(session, orgs)
    manageable = {o.id: (scope.org_manageable(ctx, o) if ctx else True) for o in orgs}
    parent_ok: dict[int, bool] = {}
    if protection and ctx:
        known = {o.id: o for o in orgs}
        parents = await org_repo.get_by_ids(session, {o.parent_id for o in orgs} - known.keys())
        for o in orgs:
            p = known.get(o.parent_id) or parents.get(o.parent_id)
            parent_ok[o.id] = p is not None and not p.is_deleted and scope.org_manageable(ctx, p)
    return {
        o.id: OrgNode(
            id=o.id,
            parent_id=o.parent_id,
            name=o.name,
            code=o.code,
            org_type=o.org_type,
            leader_user_id=o.leader_user_id,
            leader_name=leaders.get(o.leader_user_id) if o.leader_user_id else None,
            sort_order=o.sort_order,
            status=o.status,
            effective_status=eff[o.id],
            company_id=o.company_id,
            version=o.version,
            manageable=manageable.get(o.id, True),
            disable_blocked_reason=protection.disable_blocked_reason(o) if protection and manageable[o.id] else None,
            delete_blocked_reason=protection.delete_blocked_reason(o) if protection and manageable[o.id] else None,
            move_blocked_reason=(
                protection.move_blocked_reason(o, parent_ok[o.id]) if protection and manageable[o.id] else None
            ),
            created_at=o.created_at,
            children=[],
        )
        for o in orgs
    }


async def _node_of(session: AsyncSession, org: SysOrg) -> OrgNode:
    await session.refresh(org)
    return (await _to_nodes(session, [org]))[org.id]


def _build_forest[T: (OrgNode, OrgOption)](ordered: list[T]) -> list[T]:
    """按给定顺序组森林：父节点不在集合内的节点作为根。"""
    by_id = {n.id: n for n in ordered}
    roots: list[T] = []
    for n in ordered:
        parent = by_id.get(n.parent_id)
        if parent is None:
            roots.append(n)
        else:
            parent.children.append(n)
    return roots


# --------------------------------------------------------------------------- 查询


async def tree(session: AsyncSession, ctx: AuthContext, *, name: str | None, status: str | None) -> list[OrgNode]:
    visible = await org_repo.list_visible(session, scope.visible_org_filter(ctx))
    keep = visible
    if name or status:
        keyword = name.strip().casefold() if name else ""
        by_id = {o.id: o for o in visible}
        matched = [
            o for o in visible if (not keyword or keyword in o.name.casefold()) and (not status or o.status == status)
        ]
        keep_ids = {o.id for o in matched}
        for o in matched:
            keep_ids.update(a for a in _ancestor_ids(o) if a in by_id)  # 命中节点的可见祖先
        keep = [o for o in visible if o.id in keep_ids]
    protection = await org_protection.compute(session, ctx)
    nodes = await _to_nodes(session, keep, protection, ctx)
    return _build_forest([nodes[o.id] for o in keep])


async def options(
    session: AsyncSession, ctx: AuthContext, *, types: set[str] | None, include_disabled: bool
) -> list[OrgOption]:
    visible = await org_repo.list_visible(session, scope.visible_org_filter(ctx))
    eff = await _effective_statuses(session, visible)
    items = [
        OrgOption(
            id=o.id,
            parent_id=o.parent_id,
            name=o.name,
            org_type=o.org_type,
            status=o.status,
            manageable=scope.org_manageable(ctx, o),
        )
        for o in visible
        if (not types or o.org_type in types) and (include_disabled or eff[o.id] == Status.ENABLED)
    ]
    return _build_forest(items)


async def get_org(session: AsyncSession, ctx: AuthContext, org_id: int) -> OrgNode:
    org = await _get_visible(session, ctx, org_id, manage=False)
    await session.refresh(org)
    protection = await org_protection.compute(session, ctx)
    return (await _to_nodes(session, [org], protection, ctx))[org.id]


# --------------------------------------------------------------------------- 写操作


async def create_org(session: AsyncSession, ctx: AuthContext, request: Request, body: OrgCreate) -> OrgNode:
    async with oplog_scope(request, ctx, module="org", action="create", target_type="org", target_name=body.name) as h:
        parent = await _get_visible(session, ctx, body.parent_id)
        _check_hierarchy(body.org_type, parent)
        await _check_leader(session, ctx, body.leader_user_id)
        if await org_repo.name_exists(session, parent.id, body.name):
            raise BizError(*NAME_EXISTS)
        if await org_repo.code_exists(session, body.code):
            raise BizError(*CODE_EXISTS)

        org = SysOrg(
            parent_id=parent.id,
            ancestors=f"{parent.ancestors},{parent.id}",
            org_type=body.org_type,
            name=body.name,
            code=body.code,
            leader_user_id=body.leader_user_id,
            sort_order=body.sort_order,
            status=body.status,
            company_id=0,  # NOT NULL：先占位，flush 取得 id 后回填
            dept_id=0,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
        )
        session.add(org)
        await _flush_org(session)
        org.company_id = org.id if body.org_type == OrgType.COMPANY.value else parent.company_id
        org.dept_id = org.id
        await _flush_org(session)
        h.set_target(org.id, org.name)
        h.summary = {"after": _snapshot(org)}
        await event_service.publish_org_upserted(session, org)
        await session.commit()
        await _bump_epoch_safely()
        return await _node_of(session, org)


async def update_org(
    session: AsyncSession, ctx: AuthContext, request: Request, org_id: int, body: OrgUpdate
) -> OrgNode:
    async with oplog_scope(request, ctx, module="org", action="update", target_type="org", target_id=org_id) as h:
        org = await _get_visible(session, ctx, org_id, for_update=True)
        h.set_target(org.id, org.name)
        _ensure_version(org, body.version)
        before = _snapshot(org)
        if body.name != org.name and await org_repo.name_exists(session, org.parent_id, body.name, exclude_id=org.id):
            raise BizError(*NAME_EXISTS)
        if body.leader_user_id != org.leader_user_id:
            await _check_leader(session, ctx, body.leader_user_id)
        org.name = body.name
        org.leader_user_id = body.leader_user_id
        org.sort_order = body.sort_order
        org.version += 1
        org.updated_by = ctx.user_id
        await _flush_org(session)
        h.summary = {"before": before, "after": _snapshot(org)}
        await event_service.publish_org_upserted(session, org)
        await session.commit()
        return await _node_of(session, org)


async def move_org(session: AsyncSession, ctx: AuthContext, request: Request, org_id: int, body: OrgMove) -> OrgNode:
    async with oplog_scope(request, ctx, module="org", action="move", target_type="org", target_id=org_id) as h:
        org = await _get_visible(session, ctx, org_id, for_update=True)
        h.set_target(org.id, org.name)
        # 移动保护 M1~M3（5.2.0），先于目标上级相关校验；与组织树 move_blocked_reason 同源
        current_parent = await org_repo.get_active(session, org.parent_id)
        parent_ok = current_parent is not None and scope.org_manageable(ctx, current_parent)
        (await org_protection.compute(session, ctx)).check_move(org, parent_ok)
        _ensure_version(org, body.version)
        new_parent = await _get_visible(session, ctx, body.parent_id)
        if new_parent.id == org.id or f",{org.id}," in f",{new_parent.ancestors},":
            raise BizError(*MOVE_INTO_SELF)
        _check_hierarchy(org.org_type, new_parent)

        before = {"parent_id": org.parent_id, "ancestors": org.ancestors, "company_id": org.company_id}
        if new_parent.id == org.parent_id:  # 上级未变：无需任何改动
            h.suppress = True  # no-op：不写操作日志、不发事件、不 bump epoch
            return await _node_of(session, org)
        if await org_repo.name_exists(session, new_parent.id, org.name, exclude_id=org.id):
            raise BizError(*NAME_EXISTS)

        descendants = await org_repo.subtree(session, org.id)
        old_prefix = f"{org.ancestors},{org.id}"

        org.parent_id = new_parent.id
        org.ancestors = f"{new_parent.ancestors},{new_parent.id}"
        org.company_id = org.id if org.org_type == OrgType.COMPANY else new_parent.company_id
        org.version += 1
        org.updated_by = ctx.user_id
        await _flush_org(session)
        new_prefix = f"{org.ancestors},{org.id}"

        # 后代 company_id：公司节点为自身，部门取其父节点（已算出）的 company_id；父节点必在 {自身 + 已处理后代} 内
        new_company: dict[int, int] = {org.id: org.company_id}
        groups: dict[int, list[int]] = {}
        for d in sorted(descendants, key=lambda x: (len(x.ancestors), x.id)):
            cid = d.id if d.org_type in (OrgType.GROUP, OrgType.COMPANY) else new_company[d.parent_id]
            new_company[d.id] = cid
            groups.setdefault(cid, []).append(d.id)
        for cid, ids in groups.items():
            await org_repo.reparent_descendants(
                session,
                old_prefix=old_prefix,
                new_prefix=new_prefix,
                ids=ids,
                company_id=cid,
                operator_id=ctx.user_id,
            )

        # 用户 company_id 重算（自身与后代所在组织）；按目标公司分组
        orgs_by_company: dict[int, list[int]] = {}
        for oid, cid in new_company.items():
            orgs_by_company.setdefault(cid, []).append(oid)
        user_ids: list[int] = []
        for cid, oids in orgs_by_company.items():
            user_ids.extend(await user_repo.reassign_company(session, oids, cid, ctx.user_id))

        fresh = await org_repo.subtree(session, org.id, populate=True)
        users = await user_repo.get_many_fresh(session, user_ids)
        await event_service.publish_orgs_upserted(session, [org, *fresh])
        await event_service.publish_users_upserted(session, users)
        h.summary = {
            "before": before,
            "after": {"parent_id": org.parent_id, "ancestors": org.ancestors, "company_id": org.company_id},
            "affected_orgs": len(fresh) + 1,
            "affected_users": len(user_ids),
        }
        await session.commit()
        await _bump_epoch_safely()
        return await _node_of(session, org)


async def set_status(
    session: AsyncSession, ctx: AuthContext, request: Request, org_id: int, body: OrgStatusBody
) -> OrgNode:
    async with oplog_scope(request, ctx, module="org", action="status", target_type="org", target_id=org_id) as h:
        org = await _get_visible(session, ctx, org_id, for_update=True)
        h.set_target(org.id, org.name)
        if org.org_type == OrgType.GROUP:
            raise BizError(*GROUP_PROTECTED)
        disabling = body.status == Status.DISABLED.value and org.status != Status.DISABLED
        if disabling:  # 保护规则（5.2.0）：同一函数也用于树节点提示
            (await org_protection.compute(session, ctx)).check_disable(org)
        _ensure_version(org, body.version)
        if org.status == body.status:  # 状态未变化：no-op，不写日志、不吊销会话、不 bump epoch
            h.suppress = True
            return await _node_of(session, org)
        before = org.status
        org.status = body.status
        org.version += 1
        org.updated_by = ctx.user_id

        user_ids: list[int] = []
        revoked: dict[int, list[str]] = {}
        if body.status == Status.DISABLED.value:
            subtree_ids = [org.id, *(d.id for d in await org_repo.subtree(session, org.id))]
            user_ids = await user_repo.ids_in_orgs(session, subtree_ids)
            revoked = await session_service.revoke_many(session, user_ids, RevokeReason.ORG_DISABLED)
        await _flush_org(session)
        h.summary = {"before": {"status": before}, "after": {"status": org.status}, "revoked_users": len(user_ids)}
        await event_service.publish_org_upserted(session, org)
        await session.commit()

        # 即时生效：先清会话缓存，再使权限上下文失效
        for uid in user_ids:
            try:
                await session_service.purge_cache(uid, revoked.get(uid, []))
            except BizError:
                logger.error("停用组织后清理会话缓存失败 user_id=%s", uid)
        await _bump_epoch_safely()
        return await _node_of(session, org)


async def delete_org(session: AsyncSession, ctx: AuthContext, request: Request, org_id: int) -> None:
    async with oplog_scope(request, ctx, module="org", action="delete", target_type="org", target_id=org_id) as h:
        org = await _get_visible(session, ctx, org_id, for_update=True)
        h.set_target(org.id, org.name)
        (await org_protection.compute(session, ctx)).check_delete(org)  # 400114 / 403102
        if await org_repo.has_children(session, org.id):
            raise BizError(*HAS_CHILDREN)
        if await user_repo.count_in_org(session, org.id) > 0:
            raise BizError(*HAS_USERS)
        role_names, role_total = await role_repo.company_roles_owned_by(session, org.id)
        if role_total:
            raise BizError(*HAS_COMPANY_ROLES, data={"roles": role_names, "total": role_total})
        datasets = await downstream.kb_dataset_count_by_dept(org.id)  # 开关关闭 → None（跳过）；失败 → 503001
        if datasets:
            raise BizError(*HAS_DATASETS)
        removed_roles = await role_repo.remove_org_refs(session, org.id)  # CUSTOM 范围引用自动移除（方向安全：收窄）
        h.summary = {"before": _snapshot(org)}
        if removed_roles:
            h.summary["custom_role_refs_removed"] = removed_roles
        org.is_deleted = True
        org.version += 1
        org.updated_by = ctx.user_id
        await _flush_org(session)
        await event_service.publish_org_upserted(session, org)
        await session.commit()
        await _bump_epoch_safely()
