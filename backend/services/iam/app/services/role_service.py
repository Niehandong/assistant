"""角色与权限（5.4）：可见/可编辑/授权上限/可分配判定、角色增删改、授权、权限树。

对其他 service（BE-08 用户管理）的入口：

* ``assignable_roles_for(session, ctx, *, user_id=None, org_id=None) -> list[AssignableRole]``
  ``user_id`` 与 ``org_id`` 二选一（否则 400001）；目标须在操作人数据范围内（否则 404000）；
  只返回"对目标可分配"的启用角色，``assigned`` 表示用户已持有（``org_id`` 场景恒为 False）。
* ``ensure_roles_assignable(session, ctx, role_ids, *, user_id=None, org_id=None) -> list[SysRole]``
  校验 role_ids 全部可分配，否则 403121；返回对应角色（按 id 升序）。
* ``assignable_roles(session, ctx, target_company_id) -> list[SysRole]``：已知目标所属公司时的底层判定。
* ``can_manage_role(ctx, role) -> bool``：角色对操作人可见（公司级角色在可管理公司集合内）；5.3.7 中
  "用户现有角色里操作人不可管理的" = 现有角色中 ``can_manage_role`` 为 False 或不在 ``assignable_roles`` 内的部分。
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from typing import Any

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import BuiltinRole, DataScopeType, OrgType, RoleType
from app.models import SysRole
from app.repositories import org_repo, permission_repo, role_repo, scope, user_repo
from app.schemas.permission import PermissionNode, PermissionTreeData
from app.schemas.role import (
    AssignableRole,
    RoleCreate,
    RoleDetail,
    RoleGrant,
    RoleItem,
    RoleUpdate,
)
from app.schemas.user import UserItem
from app.services import authz_service
from platform_common.auth.context import AuthContext
from platform_common.auth.data_scope import in_data_scope
from platform_common.errors import BizError, CommonErrors
from platform_common.oplog import oplog_scope
from platform_common.pagination import PageParams

logger = logging.getLogger(__name__)

ROLE_CODE_EXISTS = (409121, "角色编码已存在")
ROLE_NAME_EXISTS = (409122, "角色名称已存在")
ROLE_HAS_USERS = (409123, "角色仍有关联用户，不能删除")
SELF_LOCKOUT = (409124, "保存后您将失去该页面权限，请确认")
CUSTOM_NEED_ORG = (400121, "自定义数据范围必须至少选择一个组织")
COMPANY_ROLE_NEED_OWNER = (400122, "公司级角色必须指定所属公司")
ROLES_NOT_ASSIGNABLE = (403121, "所选角色超出您的授权范围")
BUILTIN_PROTECTED = (403122, "内置角色不能删除（超级管理员角色不能修改）")
PERMISSION_EXCEEDED = (403123, "授予的权限超出您拥有的权限")
SCOPE_EXCEEDED = (403124, "数据范围超出您的数据范围")
ROLE_FORBIDDEN = (403125, "无权维护该角色")

# 数据范围等级（5.4.0）；CUSTOM 不参与等级
SCOPE_RANK: dict[str, int] = {
    DataScopeType.SELF: 1,
    DataScopeType.DEPT: 2,
    DataScopeType.DEPT_AND_CHILD: 3,
    DataScopeType.COMPANY: 4,
    DataScopeType.COMPANY_AND_CHILD: 5,
    DataScopeType.ALL: 6,
}
_RANK_TO_SCOPE = {v: k for k, v in SCOPE_RANK.items()}
# 自锁检查关注的权限：保存后失去它，操作人将无法再进入角色管理页
_LOCKOUT_WATCH = ("system:role:list",)


# --------------------------------------------------------------------------- 规则（5.4.0）


def is_global(ctx: AuthContext) -> bool:
    """超管或 ALL 范围。"""
    return ctx.is_super_admin or ctx.data_scope.all


def manageable_company_ids(ctx: AuthContext) -> list[int] | None:
    """可管理公司集合 M(op)；None 表示全部。"""
    return None if is_global(ctx) else list(ctx.data_scope.company_ids)


def _can_manage_company(ctx: AuthContext, company_id: int | None) -> bool:
    if is_global(ctx):
        return True
    return company_id is not None and company_id in ctx.data_scope.company_ids


def _visible(ctx: AuthContext, role: SysRole) -> bool:
    if role.role_type == RoleType.GROUP:
        return True
    return _can_manage_company(ctx, role.owner_company_id)


def can_manage_role(ctx: AuthContext, role: SysRole) -> bool:
    """角色对操作人可见（公司级角色须在可管理公司内）。"""
    return _visible(ctx, role)


def _editable(ctx: AuthContext, role: SysRole) -> bool:
    if role.builtin_key == BuiltinRole.SUPER_ADMIN:
        return False
    if role.role_type == RoleType.GROUP:
        return is_global(ctx)
    return _can_manage_company(ctx, role.owner_company_id)


def _owned_permissions(ctx: AuthContext) -> set[str] | None:
    """操作人拥有的权限码；None 表示不限（超管）。"""
    return None if ctx.is_super_admin else set(ctx.permissions)


async def _op_max_rank(session: AsyncSession, ctx: AuthContext) -> int:
    """操作人所有启用角色中非 CUSTOM 范围的最大等级；超管为 ALL；仅 CUSTOM 时为 SELF。"""
    if ctx.is_super_admin:
        return SCOPE_RANK[DataScopeType.ALL]
    roles = await role_repo.effective_roles_of_users(session, [ctx.user_id])
    ranks = [SCOPE_RANK[r.data_scope] for r in roles if r.data_scope in SCOPE_RANK]
    if ctx.data_scope.all:
        ranks.append(SCOPE_RANK[DataScopeType.ALL])
    return max(ranks, default=SCOPE_RANK[DataScopeType.SELF])


def _org_in_scope(ctx: AuthContext, org: Any) -> bool:
    return in_data_scope(ctx, company_id=org.company_id, dept_id=org.dept_id, owner_id=org.created_by)


async def _ensure_scope_allowed(
    session: AsyncSession,
    ctx: AuthContext,
    data_scope: str,
    custom_org_ids: Collection[int],
    *,
    existing_scope: str | None = None,
    existing_org_ids: Collection[int] = (),
) -> None:
    """数据范围授权上限：非 CUSTOM 需 rank ≤ max_rank(op)；CUSTOM 每个组织须在操作人数据范围内。
    与角色现有值相同的部分视为"未改动"，不再校验（避免有权编辑权限的人因历史值被卡住，且不构成提权）。"""
    if ctx.is_super_admin:
        return
    if data_scope == DataScopeType.CUSTOM:
        new_ids = set(custom_org_ids) - set(existing_org_ids if existing_scope == DataScopeType.CUSTOM else ())
        if not new_ids:
            return
        orgs = await org_repo.get_by_ids(session, new_ids)
        for oid in new_ids:
            org = orgs.get(oid)
            if org is None or org.is_deleted or not _org_in_scope(ctx, org):
                raise BizError(*SCOPE_EXCEEDED)
        return
    if data_scope == existing_scope:
        return
    if SCOPE_RANK[data_scope] > await _op_max_rank(session, ctx):
        raise BizError(*SCOPE_EXCEEDED)


async def _validate_custom_orgs(session: AsyncSession, data_scope: str, custom_org_ids: list[int]) -> list[int]:
    """CUSTOM 须 ≥1 个存在的组织；非 CUSTOM 返回空集合。"""
    if data_scope != DataScopeType.CUSTOM:
        return []
    if not custom_org_ids:
        raise BizError(*CUSTOM_NEED_ORG)
    orgs = await org_repo.get_by_ids(session, custom_org_ids)
    if any(oid not in orgs or orgs[oid].is_deleted for oid in custom_org_ids):
        raise BizError(CommonErrors.INVALID_PARAMS[0], "所选组织不存在")
    return list(custom_org_ids)


# --------------------------------------------------------------------------- 输出组装


async def _to_items(session: AsyncSession, ctx: AuthContext, roles: list[SysRole]) -> list[RoleItem]:
    counts = await role_repo.count_users_by_role(session, [r.id for r in roles])
    owner_ids = {r.owner_company_id for r in roles if r.owner_company_id}
    orgs = await org_repo.get_by_ids(session, owner_ids)
    return [
        RoleItem(
            id=r.id,
            code=r.code,
            name=r.name,
            role_type=r.role_type,
            owner_company_id=r.owner_company_id,
            owner_company_name=orgs[r.owner_company_id].name if r.owner_company_id in orgs else None,
            data_scope=r.data_scope,
            status=r.status,
            remark=r.remark,
            is_builtin=r.is_builtin,
            builtin_key=r.builtin_key,
            user_count=counts.get(r.id, 0),
            editable=_editable(ctx, r),
            created_at=r.created_at,
            version=r.version,
        )
        for r in roles
    ]


async def _to_detail(session: AsyncSession, ctx: AuthContext, role: SysRole) -> RoleDetail:
    item = (await _to_items(session, ctx, [role]))[0]
    perms = await role_repo.role_permissions(session, role.id)
    org_ids = await role_repo.role_org_ids(session, role.id)
    return RoleDetail(**item.model_dump(), permission_ids=sorted(perms), custom_org_ids=org_ids)


async def _get_visible(session: AsyncSession, ctx: AuthContext, role_id: int, *, for_update: bool = False) -> SysRole:
    role = await role_repo.get_role(session, role_id, for_update=for_update)
    if role is None or not _visible(ctx, role):
        raise BizError(*CommonErrors.NOT_FOUND)
    return role


def _ensure_editable(ctx: AuthContext, role: SysRole) -> None:
    if role.builtin_key == BuiltinRole.SUPER_ADMIN:
        raise BizError(*BUILTIN_PROTECTED)
    if not _editable(ctx, role):
        raise BizError(*ROLE_FORBIDDEN)


def _ensure_version(role: SysRole, version: int) -> None:
    if role.version != version:
        raise BizError(*CommonErrors.VERSION_CONFLICT)


async def _bump_epoch_safely() -> None:
    """提交后立即使全部权限上下文缓存失效；Redis 异常只记日志（缓存 TTL 兜底）。"""
    try:
        await authz_service.bump_epoch()
    except Exception:
        logger.error("递增 authz:epoch 失败", exc_info=True)


async def _lost_permissions(
    session: AsyncSession, ctx: AuthContext, role_id: int, new_codes: set[str] | None
) -> list[str]:
    """操作人自身持有该角色时，变更（授权替换 / 停用）后会失去的关键权限。new_codes=None 表示角色被停用。"""
    if ctx.is_super_admin:
        return []
    op_roles = await role_repo.effective_roles_of_users(session, [ctx.user_id])
    role_ids = {r.role_id for r in op_roles}
    if role_id not in role_ids:
        return []
    perms = await permission_repo.role_permission_codes(session, role_ids)
    after: set[str] = set()
    for rid in role_ids:
        if rid == role_id:
            after |= new_codes or set()
        else:
            after |= perms.get(rid, set())
    return [c for c in _LOCKOUT_WATCH if ctx.has_perm(c) and c not in after]


def _lockout_error(lost: list[str]) -> BizError:
    return BizError(SELF_LOCKOUT[0], SELF_LOCKOUT[1], {"lost_permissions": lost})


async def _flush_role(session: AsyncSession) -> None:
    """flush，并发下的唯一约束冲突转换为业务错误。"""
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        msg = str(exc.orig)
        if "uq_sys_role_name" in msg:
            raise BizError(*ROLE_NAME_EXISTS) from exc
        if "sys_role_code_key" in msg:
            raise BizError(*ROLE_CODE_EXISTS) from exc
        raise


# --------------------------------------------------------------------------- 查询


async def list_roles(
    session: AsyncSession,
    ctx: AuthContext,
    pp: PageParams,
    *,
    name: str | None,
    code: str | None,
    role_type: str | None,
    status: str | None,
    owner_company_id: int | None,
) -> tuple[list[RoleItem], int]:
    rows, total = await role_repo.page_roles(
        session,
        manageable_company_ids=manageable_company_ids(ctx),
        name=name,
        code=code,
        role_type=role_type,
        status=status,
        owner_company_id=owner_company_id,
        offset=pp.offset,
        limit=pp.limit,
    )
    return await _to_items(session, ctx, rows), total


async def get_role_detail(session: AsyncSession, ctx: AuthContext, role_id: int) -> RoleDetail:
    return await _to_detail(session, ctx, await _get_visible(session, ctx, role_id))


async def list_role_users(
    session: AsyncSession, ctx: AuthContext, role_id: int, pp: PageParams
) -> tuple[list[UserItem], int]:
    await _get_visible(session, ctx, role_id)
    users, total = await user_repo.page_users_of_role(
        session, role_id, scope.visible_user_filter(ctx), pp.offset, pp.limit
    )
    orgs = await org_repo.get_by_ids(session, {u.org_id for u in users} | {u.company_id for u in users})
    items = [
        UserItem(
            id=u.id,
            username=u.username,
            name=u.name,
            org_id=u.org_id,
            org_name=orgs[u.org_id].name if u.org_id in orgs else None,
            company_id=u.company_id,
            company_name=orgs[u.company_id].name if u.company_id in orgs else None,
            roles=[],
            mobile=u.mobile,
            email=u.email,
            status=u.status,
            is_builtin=u.is_builtin,
            must_change_password=u.must_change_password,
            last_login_at=u.last_login_at,
            created_at=u.created_at,
            version=u.version,
            manageable=scope.user_manageable(ctx, u),
        )
        for u in users
    ]
    return items, total


async def permission_tree(session: AsyncSession, ctx: AuthContext) -> PermissionTreeData:
    perms = await permission_repo.list_all(session)
    owned = _owned_permissions(ctx)
    nodes = {
        p.id: PermissionNode(
            id=p.id,
            code=p.code,
            name=p.name,
            perm_type=p.perm_type,
            grantable=owned is None or p.code in owned,
        )
        for p in perms
    }
    roots: list[PermissionNode] = []
    for p in perms:  # list_all 已按 (sort_order, id) 排序
        parent = nodes.get(p.parent_id)
        (parent.children if parent else roots).append(nodes[p.id])
    scope = ctx.data_scope
    can_custom = is_global(ctx) or bool(scope.company_ids or scope.org_ids or scope.include_self)
    max_rank = await _op_max_rank(session, ctx)
    return PermissionTreeData(tree=roots, max_data_scope=str(_RANK_TO_SCOPE[max_rank]), can_custom=can_custom)


# --------------------------------------------------------------------------- 可分配判定


async def assignable_roles(session: AsyncSession, ctx: AuthContext, target_company_id: int) -> list[SysRole]:
    """对"所属公司为 target_company_id 的用户"可分配的角色（5.4.0）：可见且启用；角色权限 ⊆ 操作人权限；
    数据范围满足授权上限；公司级角色要求目标公司在 owner 及其下属公司内；super_admin 仅超管可分配。"""
    candidates = await role_repo.list_enabled_visible_roles(session, manageable_company_ids(ctx))
    if not candidates:
        return []
    owned = _owned_permissions(ctx)
    target = (await org_repo.get_by_ids(session, [target_company_id])).get(target_company_id)
    target_chain: set[int] = set()
    if target is not None:
        target_chain = {int(x) for x in target.ancestors.split(",") if x} | {target.id}

    role_perms: dict[int, set[str]] = {}
    custom_orgs: dict[int, set[int]] = {}
    org_map: dict[int, Any] = {}
    max_rank = 0
    if not ctx.is_super_admin:
        role_perms = await permission_repo.role_permission_codes(session, [r.id for r in candidates])
        custom_orgs = await role_repo.role_custom_orgs(
            session, [r.id for r in candidates if r.data_scope == DataScopeType.CUSTOM]
        )
        org_map = await org_repo.get_by_ids(session, {o for s in custom_orgs.values() for o in s})
        max_rank = await _op_max_rank(session, ctx)

    result: list[SysRole] = []
    for role in candidates:
        if role.builtin_key == BuiltinRole.SUPER_ADMIN and not ctx.is_super_admin:
            continue
        if role.role_type == RoleType.COMPANY and role.owner_company_id not in target_chain:
            continue
        if owned is not None:
            if not role_perms.get(role.id, set()) <= owned:
                continue
            if role.data_scope == DataScopeType.CUSTOM:
                live = [
                    org_map[o] for o in custom_orgs.get(role.id, set()) if o in org_map and not org_map[o].is_deleted
                ]
                if not all(_org_in_scope(ctx, o) for o in live):
                    continue
            elif SCOPE_RANK.get(role.data_scope, 99) > max_rank:
                continue
        result.append(role)
    return result


async def _resolve_target(
    session: AsyncSession, ctx: AuthContext, user_id: int | None, org_id: int | None
) -> tuple[int, set[int]]:
    """二选一校验 + 数据范围校验，返回 (目标所属公司 ID, 用户已持有角色 ID 集合)。"""
    if (user_id is None) == (org_id is None):
        raise BizError(CommonErrors.INVALID_PARAMS[0], "user_id 与 org_id 必须二选一")
    if user_id is not None:
        user = await user_repo.get_by_id(session, user_id)
        if user is None or not in_data_scope(
            ctx, company_id=user.company_id, dept_id=user.dept_id, owner_id=user.created_by
        ):
            raise BizError(*CommonErrors.NOT_FOUND)
        return user.company_id, await role_repo.user_role_ids(session, user.id)
    assert org_id is not None
    org = (await org_repo.get_by_ids(session, [org_id])).get(org_id)
    if org is None or org.is_deleted or not _org_in_scope(ctx, org):
        raise BizError(*CommonErrors.NOT_FOUND)
    return org.company_id, set()


async def assignable_roles_for(
    session: AsyncSession, ctx: AuthContext, *, user_id: int | None = None, org_id: int | None = None
) -> list[AssignableRole]:
    """见模块文档。不校验操作人的功能权限码（由路由/调用方的 ``require_perm`` 负责）。"""
    company_id, assigned = await _resolve_target(session, ctx, user_id, org_id)
    roles = await assignable_roles(session, ctx, company_id)
    return [
        AssignableRole(
            id=r.id,
            name=r.name,
            code=r.code,
            role_type=r.role_type,
            data_scope=r.data_scope,
            assigned=r.id in assigned,
        )
        for r in roles
    ]


async def ensure_roles_assignable(
    session: AsyncSession,
    ctx: AuthContext,
    role_ids: Collection[int],
    *,
    user_id: int | None = None,
    org_id: int | None = None,
) -> list[SysRole]:
    """role_ids 须全部对目标可分配，否则 403121。"""
    company_id, _ = await _resolve_target(session, ctx, user_id, org_id)
    allowed = {r.id: r for r in await assignable_roles(session, ctx, company_id)}
    wanted = set(role_ids)
    if not wanted <= set(allowed):
        raise BizError(*ROLES_NOT_ASSIGNABLE)
    return [allowed[i] for i in sorted(wanted)]


async def list_assignable(
    session: AsyncSession, ctx: AuthContext, *, user_id: int | None, org_id: int | None
) -> list[AssignableRole]:
    """GET /system/roles/assignable：按场景要求不同的功能权限码（路由层为 any-of，这里区分）。"""
    if user_id is not None and org_id is None:
        if not ctx.has_perm("system:user:assign"):
            raise BizError(*CommonErrors.FORBIDDEN)
    elif org_id is not None and user_id is None:
        if not ctx.has_perm("system:user:create"):
            raise BizError(*CommonErrors.FORBIDDEN)
    return await assignable_roles_for(session, ctx, user_id=user_id, org_id=org_id)


# --------------------------------------------------------------------------- 写操作


def _role_snapshot(role: SysRole) -> dict[str, Any]:
    return {
        "code": role.code,
        "name": role.name,
        "role_type": role.role_type,
        "owner_company_id": role.owner_company_id,
        "data_scope": role.data_scope,
        "status": role.status,
        "remark": role.remark,
    }


async def create_role(session: AsyncSession, ctx: AuthContext, request: Request, body: RoleCreate) -> RoleDetail:
    async with oplog_scope(
        request, ctx, module="role", action="create", target_type="role", target_name=body.name
    ) as h:
        owner_company_id: int | None = None
        if body.role_type == "group":
            if not is_global(ctx):
                raise BizError(*ROLE_FORBIDDEN)
        else:
            if body.owner_company_id is None:
                raise BizError(*COMPANY_ROLE_NEED_OWNER)
            owner = (await org_repo.get_by_ids(session, [body.owner_company_id])).get(body.owner_company_id)
            if owner is None or owner.is_deleted or owner.org_type not in (OrgType.COMPANY, OrgType.GROUP):
                raise BizError(CommonErrors.INVALID_PARAMS[0], "所属公司不存在或不是公司节点")
            if not _can_manage_company(ctx, owner.id):
                raise BizError(*ROLE_FORBIDDEN)
            owner_company_id = owner.id

        custom_ids = await _validate_custom_orgs(session, body.data_scope, body.custom_org_ids)
        await _ensure_scope_allowed(session, ctx, body.data_scope, custom_ids)

        if await role_repo.code_exists(session, body.code):
            raise BizError(*ROLE_CODE_EXISTS)
        if await role_repo.name_exists(session, owner_company_id, body.name):
            raise BizError(*ROLE_NAME_EXISTS)

        role = SysRole(
            code=body.code,
            name=body.name,
            role_type=body.role_type,
            owner_company_id=owner_company_id,
            data_scope=body.data_scope,
            status=body.status,
            remark=body.remark,
            is_builtin=False,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
        )
        session.add(role)
        await _flush_role(session)
        if custom_ids:
            await role_repo.replace_role_orgs(session, role.id, custom_ids, ctx.user_id)
        h.set_target(role.id, role.name)
        h.summary = {"after": {**_role_snapshot(role), "custom_org_ids": custom_ids}}
        await session.commit()
        return await _to_detail(session, ctx, role)


async def update_role(
    session: AsyncSession, ctx: AuthContext, request: Request, role_id: int, body: RoleUpdate
) -> RoleDetail:
    async with oplog_scope(request, ctx, module="role", action="update", target_type="role", target_id=role_id) as h:
        role = await _get_visible(session, ctx, role_id, for_update=True)
        h.set_target(role.id, role.name)
        _ensure_editable(ctx, role)
        _ensure_version(role, body.version)
        before = _role_snapshot(role)

        status_changed = body.status is not None and body.status != role.status
        if status_changed and body.status == "disabled" and not body.confirm_self_lockout:
            lost = await _lost_permissions(session, ctx, role.id, None)
            if lost:
                raise _lockout_error(lost)
        if body.name is not None and body.name != role.name:
            if await role_repo.name_exists(session, role.owner_company_id, body.name, exclude_id=role.id):
                raise BizError(*ROLE_NAME_EXISTS)
            role.name = body.name
        if body.status is not None:
            role.status = body.status
        if "remark" in body.model_fields_set:
            role.remark = body.remark
        role.version += 1
        role.updated_by = ctx.user_id
        await _flush_role(session)
        h.summary = {"before": before, "after": _role_snapshot(role)}
        await session.commit()
        if status_changed:
            await _bump_epoch_safely()
        return await _to_detail(session, ctx, role)


async def grant_role(
    session: AsyncSession, ctx: AuthContext, request: Request, role_id: int, body: RoleGrant
) -> RoleDetail:
    async with oplog_scope(request, ctx, module="role", action="grant", target_type="role", target_id=role_id) as h:
        role = await _get_visible(session, ctx, role_id, for_update=True)
        h.set_target(role.id, role.name)
        _ensure_editable(ctx, role)
        _ensure_version(role, body.version)

        existing_perms = await role_repo.role_permissions(session, role.id)  # id → code
        existing_orgs = await role_repo.role_org_ids(session, role.id)
        custom_ids = await _validate_custom_orgs(session, body.data_scope, body.custom_org_ids)

        # 授权上限：提交集合 ⊆ 操作人权限；最终集合 = 角色现有权限中操作人不拥有的 ∪ 提交集合
        submitted = await permission_repo.get_by_ids(session, body.permission_ids)
        if len(submitted) != len(body.permission_ids):
            raise BizError(CommonErrors.INVALID_PARAMS[0], "权限点不存在")
        owned = _owned_permissions(ctx)
        final: dict[int, str] = {pid: p.code for pid, p in submitted.items()}
        if owned is not None:
            forbidden = sorted(c for c in final.values() if c not in owned)
            if forbidden:
                raise BizError(PERMISSION_EXCEEDED[0], PERMISSION_EXCEEDED[1], {"forbidden_codes": forbidden})
            final.update({pid: c for pid, c in existing_perms.items() if c not in owned})

        await _ensure_scope_allowed(
            session,
            ctx,
            body.data_scope,
            custom_ids,
            existing_scope=role.data_scope,
            existing_org_ids=existing_orgs,
        )

        if not body.confirm_self_lockout:
            lost = await _lost_permissions(session, ctx, role.id, set(final.values()))
            if lost:
                raise _lockout_error(lost)

        before_scope = role.data_scope
        await role_repo.replace_role_permissions(session, role.id, final.keys(), ctx.user_id)
        await role_repo.replace_role_orgs(session, role.id, custom_ids, ctx.user_id)
        role.data_scope = body.data_scope
        role.version += 1
        role.updated_by = ctx.user_id
        await _flush_role(session)
        old_codes, new_codes = set(existing_perms.values()), set(final.values())
        h.summary = {
            "permissions": {"added": sorted(new_codes - old_codes), "removed": sorted(old_codes - new_codes)},
            "data_scope": {"before": before_scope, "after": body.data_scope},
        }
        await session.commit()
        await _bump_epoch_safely()
        return await _to_detail(session, ctx, role)


async def delete_role(session: AsyncSession, ctx: AuthContext, request: Request, role_id: int) -> None:
    async with oplog_scope(request, ctx, module="role", action="delete", target_type="role", target_id=role_id) as h:
        role = await _get_visible(session, ctx, role_id, for_update=True)
        h.set_target(role.id, role.name)
        if role.is_builtin:
            raise BizError(*BUILTIN_PROTECTED)
        if not _editable(ctx, role):
            raise BizError(*ROLE_FORBIDDEN)
        count = (await role_repo.count_users_by_role(session, [role.id])).get(role.id, 0)
        if count:
            raise BizError(ROLE_HAS_USERS[0], ROLE_HAS_USERS[1], {"user_count": count})
        h.summary = {"before": _role_snapshot(role)}
        role.is_deleted = True
        role.updated_by = ctx.user_id
        await role_repo.replace_role_permissions(session, role.id, [], ctx.user_id)
        await role_repo.replace_role_orgs(session, role.id, [], ctx.user_id)
        await session.flush()
        await session.commit()
        await _bump_epoch_safely()


__all__ = [
    "assignable_roles",
    "assignable_roles_for",
    "can_manage_role",
    "create_role",
    "delete_role",
    "ensure_roles_assignable",
    "get_role_detail",
    "grant_role",
    "is_global",
    "list_assignable",
    "list_role_users",
    "list_roles",
    "manageable_company_ids",
    "permission_tree",
    "update_role",
]
