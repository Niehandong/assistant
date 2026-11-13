"""iam 只读副本（open.user_ref / open.org_ref）的写入与查询。

写入一律按 ``source_updated_at`` 比较：只接受比库内更新的数据（旧事件、乱序事件、重复事件均不覆盖）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OrgRef, UserRef
from app.schemas.ref_sync import OrgRefPayload, UserRefPayload

_USER_FIELDS = ("username", "name", "status", "is_deleted", "org_id", "company_id")
_ORG_FIELDS = ("parent_id", "ancestors", "org_type", "name", "code", "status", "is_deleted", "company_id", "sort_order")


def _latest_per_id[T: (UserRefPayload, OrgRefPayload)](items: Sequence[T]) -> list[T]:
    """同一批次内同 id 只保留 updated_at 最大的（ON CONFLICT 不允许同语句重复命中同一行）。"""
    best: dict[int, T] = {}
    for it in items:
        cur = best.get(it.id)
        if cur is None or it.updated_at > cur.updated_at:
            best[it.id] = it
    return list(best.values())


async def _upsert[T: (UserRefPayload, OrgRefPayload)](
    session: AsyncSession, model: type[UserRef] | type[OrgRef], fields: tuple[str, ...], items: Sequence[T]
) -> list[int]:
    """批量 upsert，返回**实际被写入**（新增或更新）的 id 列表。"""
    rows = _latest_per_id(items)
    if not rows:
        return []
    values: list[dict[str, Any]] = [
        {"id": r.id, "source_updated_at": r.updated_at, **{f: getattr(r, f) for f in fields}} for r in rows
    ]
    stmt = insert(model).values(values)
    excluded = stmt.excluded
    upsert = stmt.on_conflict_do_update(
        index_elements=[model.id],
        set_={
            **{f: getattr(excluded, f) for f in fields},
            "source_updated_at": excluded.source_updated_at,
            "updated_at": func.now(),
        },
        where=(model.source_updated_at.is_(None)) | (model.source_updated_at < excluded.source_updated_at),
    ).returning(model.id)
    return list((await session.execute(upsert)).scalars().all())


async def upsert_users(session: AsyncSession, items: Sequence[UserRefPayload]) -> list[int]:
    return await _upsert(session, UserRef, _USER_FIELDS, items)


async def upsert_orgs(session: AsyncSession, items: Sequence[OrgRefPayload]) -> list[int]:
    return await _upsert(session, OrgRef, _ORG_FIELDS, items)


async def count_users(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(UserRef))).scalar_one())


async def count_orgs(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(OrgRef))).scalar_one())


async def users_by_ids(session: AsyncSession, ids: Sequence[int]) -> dict[int, UserRef]:
    """按 id 批量取用户副本（含已删除），供审计/日志展示创建人。"""
    if not ids:
        return {}
    rows = (await session.execute(select(UserRef).where(UserRef.id.in_(list(set(ids)))))).scalars().all()
    return {u.id: u for u in rows}


async def orgs_by_ids(session: AsyncSession, ids: Sequence[int]) -> dict[int, OrgRef]:
    """按 id 批量取组织副本（含已删除），供审计展示公司/部门名称。"""
    if not ids:
        return {}
    rows = (await session.execute(select(OrgRef).where(OrgRef.id.in_(list(set(ids)))))).scalars().all()
    return {o.id: o for o in rows}


__all__ = ["count_orgs", "count_users", "orgs_by_ids", "upsert_orgs", "upsert_users", "users_by_ids"]
