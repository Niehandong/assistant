"""知识库分配（F-10）。

* 查看名单：ACL 可编辑；新增/修改/移除/可分配候选：ACL 所有者（并发下锁知识库行再校验）。
* 可分配范围：所有者当前所属公司 C（``ctx.company_id``）及其下属所有组织；C 为集团节点（集团本部）时全集团。
  范围基于 org_ref 子树实时计算；成员动态生效由 ACL 基于 AuthContext 判定，不落成员快照。
* 对象被删除后分配自动失效：记录保留，``target_valid=false``，ACL 不受影响（组织/用户无人命中），仅可移除。
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dataset, DatasetAssignment, OrgRef
from app.repositories import assignment_repo as repo
from app.repositories.dataset_acl import require_dataset
from app.schemas.assignment import (
    AssignableOrgNode,
    AssignableUser,
    AssignmentCreate,
    AssignmentItem,
    AssignmentUpdate,
    UserBrief,
)
from platform_common.auth.context import AuthContext
from platform_common.errors import BizError
from platform_common.oplog import oplog_scope
from platform_common.pagination import PageParams

ERR_SELF = (400401, "不能分配给所有者本人")
ERR_OUT_OF_SCOPE = (400402, "分配对象不在可分配范围内")
ERR_DUP = (409401, "该对象已在分配名单中")
UQ_ASSIGN = "uq_dataset_assignment_target"


async def _is_group(session: AsyncSession, company_id: int) -> bool:
    org = await repo.get_org(session, company_id)
    return org is not None and org.org_type == "group"


# ---------------------------------------------------------------- 序列化


def _org_path(org: OrgRef, orgs: dict[int, OrgRef]) -> str:
    """祖级名称 + 自身，集团节点不计入（如 ``A公司/测试部``）；自身是集团时只显示集团名。"""
    names = []
    for part in org.ancestors.split(","):
        if part and part != "0" and int(part) in orgs and orgs[int(part)].org_type != "group":
            names.append(orgs[int(part)].name)
    names.append(org.name)
    return "/".join(names)


async def _items(session: AsyncSession, rows: list[DatasetAssignment]) -> list[AssignmentItem]:
    users = await repo.users_by_ids(
        session, {a.target_id for a in rows if a.target_type == "user"} | {a.created_by for a in rows}
    )
    first = {a.target_id for a in rows if a.target_type != "user"} | {u.org_id for u in users.values()}
    orgs = await repo.orgs_by_ids(session, first)
    ancestors = {int(p) for org in orgs.values() for p in org.ancestors.split(",") if p and p != "0"}
    orgs |= await repo.orgs_by_ids(session, ancestors - set(orgs))  # 路径只需名称，两轮即可

    items: list[AssignmentItem] = []
    for a in rows:
        name, path, valid = "未知对象", None, False
        if a.target_type == "user":
            u = users.get(a.target_id)
            if u is not None:
                name, valid = u.name, not u.is_deleted
                home = orgs.get(u.org_id)
                path = _org_path(home, orgs) if home else None
        else:
            target_org = orgs.get(a.target_id)
            if target_org is not None:
                name, valid = target_org.name, not target_org.is_deleted
                path = _org_path(target_org, orgs)
        creator = users.get(a.created_by)
        items.append(
            AssignmentItem(
                id=a.id,
                target_type=a.target_type,  # type: ignore[arg-type]
                target_id=a.target_id,
                target_name=name,
                target_path=path,
                target_valid=valid,
                include_children=a.include_children,
                permission=a.permission,  # type: ignore[arg-type]
                created_by=UserBrief(id=a.created_by, name=creator.name if creator else "未知用户"),
                created_at=a.created_at,
            )
        )
    return items


async def _one(session: AsyncSession, row: DatasetAssignment) -> AssignmentItem:
    return (await _items(session, [row]))[0]


# ---------------------------------------------------------------- 查询


async def list_for_dataset(session: AsyncSession, dataset_id: int) -> list[AssignmentItem]:
    """不校验 ACL 的名单（管理视图详情复用）。"""
    return await _items(session, list(await repo.list_assignments(session, dataset_id)))


async def list_assignments(session: AsyncSession, ctx: AuthContext, dataset_id: int) -> list[AssignmentItem]:
    await require_dataset(session, ctx, dataset_id, "edit")
    return await _items(session, list(await repo.list_assignments(session, dataset_id)))


async def assignable_orgs(session: AsyncSession, ctx: AuthContext, dataset_id: int) -> list[AssignableOrgNode]:
    await require_dataset(session, ctx, dataset_id, "owner")
    rows = await repo.list_orgs_in_scope(session, ctx.company_id, await _is_group(session, ctx.company_id))
    nodes = {
        o.id: AssignableOrgNode(
            id=o.id,
            parent_id=o.parent_id,
            name=o.name,
            org_type=o.org_type,  # type: ignore[arg-type]
            status=o.status,  # type: ignore[arg-type]
            children=[],
        )
        for o in rows
    }
    roots: list[AssignableOrgNode] = []
    for o in rows:  # rows 已按 sort_order, id 排序
        parent = nodes.get(o.parent_id)
        (parent.children if parent is not None else roots).append(nodes[o.id])
    return roots


async def assignable_users(
    session: AsyncSession,
    ctx: AuthContext,
    dataset_id: int,
    *,
    keyword: str | None,
    org_id: int | None,
    pp: PageParams,
) -> tuple[list[AssignableUser], int]:
    await require_dataset(session, ctx, dataset_id, "owner")
    rows, total = await repo.page_users_in_scope(
        session,
        company_id=ctx.company_id,
        is_group=await _is_group(session, ctx.company_id),
        exclude_user_id=ctx.user_id,
        keyword=keyword,
        org_id=org_id,
        offset=pp.offset,
        limit=pp.limit,
    )
    return [
        AssignableUser(id=u.id, username=u.username, name=u.name, org_name=o, company_name=c) for u, o, c in rows
    ], total


# ---------------------------------------------------------------- 写操作


async def _validate_target(
    session: AsyncSession, ctx: AuthContext, dataset: Dataset, target_type: str, target_id: int
) -> str:
    """校验分配对象，返回对象名称。"""
    is_group = await _is_group(session, ctx.company_id)
    if target_type == "user":
        if target_id == dataset.owner_id:
            raise BizError(*ERR_SELF)
        user = await repo.get_user(session, target_id)
        if user is None or user.is_deleted or user.status != "enabled":
            raise BizError(*ERR_OUT_OF_SCOPE)
        if not await repo.org_in_scope(session, user.org_id, ctx.company_id, is_group):
            raise BizError(*ERR_OUT_OF_SCOPE)
        return user.name
    org = await repo.get_org(session, target_id)
    allowed = ("dept",) if target_type == "dept" else ("company", "group")
    if org is None or org.is_deleted or org.org_type not in allowed:
        raise BizError(*ERR_OUT_OF_SCOPE)
    if not await repo.org_in_scope(session, org.id, ctx.company_id, is_group):
        raise BizError(*ERR_OUT_OF_SCOPE)
    return org.name


def _default_include(target_type: str, value: bool | None) -> bool:
    if target_type == "user":
        return False
    if value is None:
        return target_type == "dept"
    return value


async def create_assignment(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, body: AssignmentCreate
) -> AssignmentItem:
    async with oplog_scope(
        request, ctx, module="dataset", action="assign_create", target_type="dataset", target_id=dataset_id
    ) as h:
        ds = await require_dataset(session, ctx, dataset_id, "owner", for_update=True)
        h.set_target(ds.id, ds.name)
        target_name = await _validate_target(session, ctx, ds, body.target_type, body.target_id)
        if await repo.exists_target(session, ds.id, body.target_type, body.target_id):
            raise BizError(*ERR_DUP)
        row = DatasetAssignment(
            dataset_id=ds.id,
            target_type=body.target_type,
            target_id=body.target_id,
            include_children=_default_include(body.target_type, body.include_children),
            permission=body.permission,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
        )
        session.add(row)
        await _commit(session)
        await session.refresh(row)
        h.summary = _summary(row, target_name)
        return await _one(session, row)


async def update_assignment(
    session: AsyncSession,
    ctx: AuthContext,
    request: Request,
    dataset_id: int,
    assignment_id: int,
    body: AssignmentUpdate,
) -> AssignmentItem:
    async with oplog_scope(
        request, ctx, module="dataset", action="assign_update", target_type="dataset", target_id=dataset_id
    ) as h:
        ds = await require_dataset(session, ctx, dataset_id, "owner", for_update=True)
        h.set_target(ds.id, ds.name)
        row = await repo.get_assignment(session, ds.id, assignment_id)
        if row is None:
            raise BizError(404000, "无权限或数据不存在")
        item = await _one(session, row)
        if not item.target_valid:  # 失效对象只能移除
            raise BizError(*ERR_OUT_OF_SCOPE)
        before = {"permission": row.permission, "include_children": row.include_children}
        row.permission = body.permission
        row.include_children = _default_include(row.target_type, body.include_children)
        row.updated_by = ctx.user_id
        await _commit(session)
        await session.refresh(row)
        h.summary = {
            "target": {"type": row.target_type, "id": row.target_id, "name": item.target_name},
            "before": before,
            "after": {"permission": row.permission, "include_children": row.include_children},
        }
        return await _one(session, row)


async def delete_assignment(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, assignment_id: int
) -> None:
    async with oplog_scope(
        request, ctx, module="dataset", action="assign_delete", target_type="dataset", target_id=dataset_id
    ) as h:
        ds = await require_dataset(session, ctx, dataset_id, "owner", for_update=True)
        h.set_target(ds.id, ds.name)
        row = await repo.get_assignment(session, ds.id, assignment_id)
        if row is None:
            raise BizError(404000, "无权限或数据不存在")
        item = await _one(session, row)
        row.is_deleted = True
        row.updated_by = ctx.user_id
        await session.commit()
        h.summary = _summary(row, item.target_name)


def _summary(row: DatasetAssignment, name: str) -> dict[str, Any]:
    return {
        "target": {"type": row.target_type, "id": row.target_id, "name": name},
        "permission": row.permission,
        "include_children": row.include_children,
    }


async def _commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if UQ_ASSIGN in str(getattr(exc.orig, "constraint_name", "") or exc.orig):
            raise BizError(*ERR_DUP) from exc
        raise
