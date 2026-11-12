"""管理视图查询：数据范围由 ``data_scope_filter`` 在 repository 层统一注入（company_id / dept_id / owner_id）。

管理视图独立于日常 ACL，不复用 ``dataset_acl``。所有者状态以 ``user_ref`` 左连接判定：
缺失或已删除 → deleted；未删除且 status≠enabled → disabled；其余 enabled。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Dataset, DatasetAssignment, OrgRef, UserRef
from app.repositories.assignment_repo import descendant_cond
from app.repositories.dataset_repo import like_pattern
from platform_common.auth.context import AuthContext
from platform_common.auth.data_scope import data_scope_filter

OwnerStatusLit = Literal["enabled", "disabled", "deleted"]


def visible_cond(ctx: AuthContext) -> ColumnElement[bool]:
    """管理视图可见：未删除且在数据范围内（SELF 仅指当前所有者为本人，无任何例外）。"""
    return and_(
        Dataset.is_deleted.is_(False),
        data_scope_filter(ctx, company_col=Dataset.company_id, dept_col=Dataset.dept_id, owner_col=Dataset.owner_id),
    )


def _is_deleted_owner() -> ColumnElement[bool]:
    return or_(UserRef.id.is_(None), UserRef.is_deleted.is_(True))


def _is_disabled_owner() -> ColumnElement[bool]:
    return and_(UserRef.id.is_not(None), UserRef.is_deleted.is_(False), UserRef.status != "enabled")


def owner_status_of(user: UserRef | None) -> OwnerStatusLit:
    if user is None or user.is_deleted:
        return "deleted"
    return "enabled" if user.status == "enabled" else "disabled"


@dataclass
class AdminFilter:
    keyword: str | None = None
    owner_keyword: str | None = None
    owner_id: int | None = None
    org_id: int | None = None
    owner_status: OwnerStatusLit | None = None
    pending_handover: bool = False


async def get_visible(
    session: AsyncSession, ctx: AuthContext, dataset_id: int, *, for_update: bool = False
) -> Dataset | None:
    stmt = select(Dataset).where(Dataset.id == dataset_id, visible_cond(ctx))
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def lock_visible_owned_by(
    session: AsyncSession, ctx: AuthContext, from_user_id: int, ids: Sequence[int] | None
) -> list[Dataset]:
    """加锁读取 from_user 名下范围内的知识库（按 id 升序，避免并发批量操作死锁）。"""
    stmt = select(Dataset).where(Dataset.owner_id == from_user_id, visible_cond(ctx))
    if ids is not None:
        stmt = stmt.where(Dataset.id.in_(set(ids)))
    stmt = stmt.order_by(Dataset.id).with_for_update()
    return list((await session.execute(stmt)).scalars().all())


async def page_datasets(
    session: AsyncSession, ctx: AuthContext, f: AdminFilter, *, offset: int, limit: int
) -> tuple[list[Dataset], int]:
    conds: list[ColumnElement[bool]] = [visible_cond(ctx)]
    if f.keyword:
        conds.append(Dataset.name.like(like_pattern(f.keyword), escape="\\"))
    if f.owner_id is not None:
        conds.append(Dataset.owner_id == f.owner_id)
    if f.owner_keyword:
        pat = like_pattern(f.owner_keyword)
        conds.append(or_(UserRef.name.like(pat, escape="\\"), UserRef.username.like(pat, escape="\\")))
    if f.org_id is not None:
        conds.append(Dataset.dept_id.in_(select(OrgRef.id).where(descendant_cond(f.org_id))))
    if f.owner_status == "deleted":
        conds.append(_is_deleted_owner())
    elif f.owner_status == "disabled":
        conds.append(_is_disabled_owner())
    elif f.owner_status == "enabled":
        conds.append(and_(UserRef.id.is_not(None), UserRef.is_deleted.is_(False), UserRef.status == "enabled"))
    if f.pending_handover:
        conds.append(or_(_is_deleted_owner(), _is_disabled_owner()))

    base = select(Dataset).outerjoin(UserRef, UserRef.id == Dataset.owner_id).where(*conds)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        (await session.execute(base.order_by(Dataset.updated_at.desc(), Dataset.id.desc()).offset(offset).limit(limit)))
        .scalars()
        .all()
    )
    return list(rows), int(total)


async def assignment_counts(session: AsyncSession, dataset_ids: Sequence[int]) -> dict[int, int]:
    if not dataset_ids:
        return {}
    rows = (
        await session.execute(
            select(DatasetAssignment.dataset_id, func.count())
            .where(DatasetAssignment.dataset_id.in_(set(dataset_ids)), DatasetAssignment.is_deleted.is_(False))
            .group_by(DatasetAssignment.dataset_id)
        )
    ).all()
    return {int(r[0]): int(r[1]) for r in rows}


async def page_receivers(
    session: AsyncSession, ctx: AuthContext, keyword: str | None, *, offset: int, limit: int
) -> tuple[list[tuple[UserRef, str | None, str | None]], int]:
    """接收人候选：数据范围内（user_ref.company_id / org_id / id）、启用、未删除。"""
    org = aliased(OrgRef)
    comp = aliased(OrgRef)
    conds: list[ColumnElement[bool]] = [
        UserRef.is_deleted.is_(False),
        UserRef.status == "enabled",
        data_scope_filter(ctx, company_col=UserRef.company_id, dept_col=UserRef.org_id, owner_col=UserRef.id),
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


async def list_owners(
    session: AsyncSession, ctx: AuthContext, keyword: str | None, *, limit: int
) -> list[tuple[int, UserRef | None, int]]:
    """范围内知识库的所有者（含停用/删除/副本缺失）及其知识库数。"""
    conds: list[ColumnElement[bool]] = [visible_cond(ctx)]
    if keyword:
        pat = like_pattern(keyword)
        conds.append(or_(UserRef.name.like(pat, escape="\\"), UserRef.username.like(pat, escape="\\")))
    cnt = func.count(Dataset.id)
    rows = (
        await session.execute(
            select(Dataset.owner_id, cnt)
            .outerjoin(UserRef, UserRef.id == Dataset.owner_id)
            .where(*conds)
            .group_by(Dataset.owner_id)
            .order_by(cnt.desc(), Dataset.owner_id)
            .limit(limit)
        )
    ).all()
    owner_ids = [int(r[0]) for r in rows]
    users = {}
    if owner_ids:
        users = {u.id: u for u in (await session.execute(select(UserRef).where(UserRef.id.in_(owner_ids)))).scalars()}
    return [(int(r[0]), users.get(int(r[0])), int(r[1])) for r in rows]
