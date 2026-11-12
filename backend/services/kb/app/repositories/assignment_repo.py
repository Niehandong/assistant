"""分配与可分配范围查询（依赖 user_ref / org_ref 只读副本）。"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import ColumnElement, Select, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import DatasetAssignment, OrgRef, UserRef
from app.repositories.dataset_repo import like_pattern


def _descendant_cond(root_id: int) -> ColumnElement[bool]:
    """org 为 root 本身或其下级（ancestors 为祖级路径，不含自身）。"""
    return or_(OrgRef.id == root_id, func.concat(",", OrgRef.ancestors, ",").like(f"%,{int(root_id)},%"))


descendant_cond = _descendant_cond  # 供管理视图的组织筛选复用


def scope_cond(company_id: int, is_group: bool) -> ColumnElement[bool]:
    """可分配范围：所有者所属公司及其下属；所属为集团节点（集团本部）时为全集团。"""
    return true() if is_group else _descendant_cond(company_id)


def scope_org_ids(company_id: int, is_group: bool) -> Select[tuple[int]]:
    return select(OrgRef.id).where(OrgRef.is_deleted.is_(False), scope_cond(company_id, is_group))


async def get_org(session: AsyncSession, org_id: int) -> OrgRef | None:
    return (await session.execute(select(OrgRef).where(OrgRef.id == org_id))).scalar_one_or_none()


async def get_user(session: AsyncSession, user_id: int) -> UserRef | None:
    return (await session.execute(select(UserRef).where(UserRef.id == user_id))).scalar_one_or_none()


async def org_in_scope(session: AsyncSession, org_id: int, company_id: int, is_group: bool) -> bool:
    stmt = scope_org_ids(company_id, is_group).where(OrgRef.id == org_id).limit(1)
    return (await session.execute(stmt)).first() is not None


async def list_orgs_in_scope(session: AsyncSession, company_id: int, is_group: bool) -> Sequence[OrgRef]:
    stmt = (
        select(OrgRef)
        .where(OrgRef.is_deleted.is_(False), scope_cond(company_id, is_group))
        .order_by(OrgRef.sort_order, OrgRef.id)
    )
    return (await session.execute(stmt)).scalars().all()


async def page_users_in_scope(
    session: AsyncSession,
    *,
    company_id: int,
    is_group: bool,
    exclude_user_id: int,
    keyword: str | None,
    org_id: int | None,
    offset: int,
    limit: int,
) -> tuple[list[tuple[UserRef, str | None, str | None]], int]:
    org = aliased(OrgRef)
    comp = aliased(OrgRef)
    org_ids = scope_org_ids(company_id, is_group)
    if org_id is not None:
        org_ids = org_ids.where(_descendant_cond(org_id))
    conds: list[ColumnElement[bool]] = [
        UserRef.is_deleted.is_(False),
        UserRef.status == "enabled",
        UserRef.id != exclude_user_id,
        UserRef.org_id.in_(org_ids),
    ]
    if keyword:
        pat = like_pattern(keyword)
        conds.append(or_(UserRef.name.like(pat, escape="\\"), UserRef.username.like(pat, escape="\\")))
    total = (await session.execute(select(func.count()).select_from(UserRef).where(*conds))).scalar_one()
    rows = (
        await session.execute(
            select(UserRef, org.name, comp.name)
            .outerjoin(org, org.id == UserRef.org_id)
            .outerjoin(comp, comp.id == UserRef.company_id)
            .where(*conds)
            .order_by(UserRef.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return [(r[0], r[1], r[2]) for r in rows], int(total)


# ---------------------------------------------------------------- 分配记录


async def list_assignments(session: AsyncSession, dataset_id: int) -> Sequence[DatasetAssignment]:
    stmt = (
        select(DatasetAssignment)
        .where(DatasetAssignment.dataset_id == dataset_id, DatasetAssignment.is_deleted.is_(False))
        .order_by(DatasetAssignment.created_at, DatasetAssignment.id)
    )
    return (await session.execute(stmt)).scalars().all()


async def get_assignment(session: AsyncSession, dataset_id: int, assignment_id: int) -> DatasetAssignment | None:
    stmt = select(DatasetAssignment).where(
        DatasetAssignment.id == assignment_id,
        DatasetAssignment.dataset_id == dataset_id,
        DatasetAssignment.is_deleted.is_(False),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def exists_target(session: AsyncSession, dataset_id: int, target_type: str, target_id: int) -> bool:
    stmt = select(DatasetAssignment.id).where(
        DatasetAssignment.dataset_id == dataset_id,
        DatasetAssignment.target_type == target_type,
        DatasetAssignment.target_id == target_id,
        DatasetAssignment.is_deleted.is_(False),
    )
    return (await session.execute(stmt.limit(1))).first() is not None


async def orgs_by_ids(session: AsyncSession, ids: set[int]) -> dict[int, OrgRef]:
    if not ids:
        return {}
    rows = (await session.execute(select(OrgRef).where(OrgRef.id.in_(ids)))).scalars().all()
    return {o.id: o for o in rows}


async def users_by_ids(session: AsyncSession, ids: set[int]) -> dict[int, UserRef]:
    if not ids:
        return {}
    rows = (await session.execute(select(UserRef).where(UserRef.id.in_(ids)))).scalars().all()
    return {u.id: u for u in rows}
