"""知识库查询。日常列表按 ACL（所有者 + 被分配），**不**按数据权限；管理视图在 BE-23 另行实现。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import ColumnElement, case, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AiModel, ChildChunk, Dataset, DatasetAssignment, Document, OrgRef, Segment, UserRef
from app.repositories.dataset_acl import accessible_dataset_ids_subquery, edit_dataset_ids_subquery
from platform_common.auth.context import AuthContext

SortBy = Literal["updated_at", "name", "doc_count"]


def like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def permission_expr(ctx: AuthContext) -> ColumnElement[str]:
    """列表行的"我的权限"：所有者 > 可编辑分配 > 只读。"""
    return case(
        (Dataset.owner_id == ctx.user_id, "owner"),
        (Dataset.id.in_(edit_dataset_ids_subquery(ctx)), "edit"),
        else_="read",
    )


@dataclass
class DatasetFilter:
    keyword: str | None = None
    my_permission: str | None = None
    owner_keyword: str | None = None
    chunk_mode: str | None = None
    only_owned: bool = False
    sort_by: SortBy = "updated_at"
    sort_desc: bool = True


async def page_my_datasets(
    session: AsyncSession, ctx: AuthContext, f: DatasetFilter, *, offset: int, limit: int
) -> tuple[list[tuple[Dataset, str]], int]:
    perm = permission_expr(ctx).label("perm")
    conds: list[ColumnElement[bool]] = [Dataset.id.in_(accessible_dataset_ids_subquery(ctx))]
    if f.keyword:
        conds.append(Dataset.name.like(like_pattern(f.keyword), escape="\\"))
    if f.only_owned:
        conds.append(Dataset.owner_id == ctx.user_id)
    if f.my_permission:
        conds.append(permission_expr(ctx) == f.my_permission)
    if f.owner_keyword:
        pat = like_pattern(f.owner_keyword)
        conds.append(
            Dataset.owner_id.in_(
                select(UserRef.id).where(
                    or_(UserRef.name.like(pat, escape="\\"), UserRef.username.like(pat, escape="\\"))
                )
            )
        )
    if f.chunk_mode == "unset":
        conds.append(Dataset.chunk_mode.is_(None))
    elif f.chunk_mode:
        conds.append(Dataset.chunk_mode == f.chunk_mode)

    total = (await session.execute(select(func.count()).select_from(Dataset).where(*conds))).scalar_one()
    col = {"updated_at": Dataset.updated_at, "name": Dataset.name, "doc_count": Dataset.doc_count}[f.sort_by]
    order = col.desc() if f.sort_desc else col.asc()
    rows = (
        await session.execute(
            select(Dataset, perm).where(*conds).order_by(order, Dataset.id.desc()).offset(offset).limit(limit)
        )
    ).all()
    return [(r[0], r[1]) for r in rows], int(total)


async def page_options(
    session: AsyncSession, ctx: AuthContext, keyword: str | None, *, offset: int, limit: int
) -> tuple[list[tuple[int, str, str]], int]:
    conds: list[ColumnElement[bool]] = [Dataset.id.in_(accessible_dataset_ids_subquery(ctx))]
    if keyword:
        conds.append(Dataset.name.like(like_pattern(keyword), escape="\\"))
    total = (await session.execute(select(func.count()).select_from(Dataset).where(*conds))).scalar_one()
    rows = (
        await session.execute(
            select(Dataset.id, Dataset.name, permission_expr(ctx))
            .where(*conds)
            .order_by(Dataset.updated_at.desc(), Dataset.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return [(int(r[0]), r[1], r[2]) for r in rows], int(total)


async def owners_by_id(session: AsyncSession, ids: Sequence[int]) -> dict[int, UserRef]:
    if not ids:
        return {}
    rows = (await session.execute(select(UserRef).where(UserRef.id.in_(set(ids))))).scalars().all()
    return {u.id: u for u in rows}


async def models_by_id(session: AsyncSession, ids: Sequence[int]) -> dict[int, AiModel]:
    """含已删除的模型（被引用的模型不可删除，理论上不会出现；保持健壮）。"""
    if not ids:
        return {}
    rows = (await session.execute(select(AiModel).where(AiModel.id.in_(set(ids))))).scalars().all()
    return {m.id: m for m in rows}


async def orgs_by_id(session: AsyncSession, ids: Sequence[int]) -> dict[int, OrgRef]:
    if not ids:
        return {}
    rows = (await session.execute(select(OrgRef).where(OrgRef.id.in_(set(ids))))).scalars().all()
    return {o.id: o for o in rows}


async def assignment_count(session: AsyncSession, dataset_id: int) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(DatasetAssignment)
                .where(DatasetAssignment.dataset_id == dataset_id, DatasetAssignment.is_deleted.is_(False))
            )
        ).scalar_one()
    )


async def name_taken(session: AsyncSession, owner_id: int, name: str, *, exclude_id: int | None = None) -> bool:
    stmt = select(Dataset.id).where(Dataset.owner_id == owner_id, Dataset.name == name, Dataset.is_deleted.is_(False))
    if exclude_id is not None:
        stmt = stmt.where(Dataset.id != exclude_id)
    return (await session.execute(stmt.limit(1))).first() is not None


async def taken_names(session: AsyncSession, owner_id: int, names: Sequence[str]) -> set[str]:
    """``owner_id`` 名下未删除知识库中已占用的名称（批量转移的同名检查）。"""
    if not names:
        return set()
    stmt = select(Dataset.name).where(
        Dataset.owner_id == owner_id, Dataset.is_deleted.is_(False), Dataset.name.in_(set(names))
    )
    return set((await session.execute(stmt)).scalars().all())


async def has_documents(session: AsyncSession, dataset_id: int) -> bool:
    return (
        await session.execute(select(exists().where(Document.dataset_id == dataset_id, Document.is_deleted.is_(False))))
    ).scalar_one()


async def soft_delete_cascade(session: AsyncSession, dataset_id: int, operator_id: int) -> None:
    """知识库下的分配、文档、分段、子块逻辑删除；分段/子块 search_enabled=false；文档 process_attempt+1。"""
    await session.execute(
        update(ChildChunk)
        .where(ChildChunk.dataset_id == dataset_id, ChildChunk.is_deleted.is_(False))
        .values(is_deleted=True, search_enabled=False, updated_by=operator_id)
    )
    await session.execute(
        update(Segment)
        .where(Segment.dataset_id == dataset_id, Segment.is_deleted.is_(False))
        .values(is_deleted=True, search_enabled=False, updated_by=operator_id)
    )
    await session.execute(
        update(Document)
        .where(Document.dataset_id == dataset_id, Document.is_deleted.is_(False))
        .values(is_deleted=True, process_attempt=Document.process_attempt + 1, updated_by=operator_id)
    )
    await session.execute(
        update(DatasetAssignment)
        .where(DatasetAssignment.dataset_id == dataset_id, DatasetAssignment.is_deleted.is_(False))
        .values(is_deleted=True, updated_by=operator_id)
    )
