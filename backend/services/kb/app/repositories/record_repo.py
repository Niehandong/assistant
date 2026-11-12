"""召回测试记录 kb.retrieval_record（仅本人可见；每人每库保留最近 20 条，超出物理删除）。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RetrievalRecord

KEEP_RECENT = 20


async def add_record(
    session: AsyncSession,
    *,
    dataset_id: int,
    user_id: int,
    query: str,
    config: dict[str, Any],
    result_count: int,
) -> RetrievalRecord:
    """插入一条记录并删除该用户在该库第 ``KEEP_RECENT`` 条之后的旧记录（不 commit）。"""
    rec = RetrievalRecord(
        dataset_id=dataset_id,
        query=query,
        retrieval_config=config,
        result_count=result_count,
        created_by=user_id,
        updated_by=user_id,
    )
    session.add(rec)
    await session.flush()
    keep = (
        select(RetrievalRecord.id)
        .where(RetrievalRecord.dataset_id == dataset_id, RetrievalRecord.created_by == user_id)
        .order_by(RetrievalRecord.created_at.desc(), RetrievalRecord.id.desc())
        .limit(KEEP_RECENT)
    )
    await session.execute(
        delete(RetrievalRecord).where(
            RetrievalRecord.dataset_id == dataset_id,
            RetrievalRecord.created_by == user_id,
            RetrievalRecord.id.not_in(keep),
        )
    )
    return rec


async def list_recent(session: AsyncSession, dataset_id: int, user_id: int) -> Sequence[RetrievalRecord]:
    stmt = (
        select(RetrievalRecord)
        .where(
            RetrievalRecord.dataset_id == dataset_id,
            RetrievalRecord.created_by == user_id,
            RetrievalRecord.is_deleted.is_(False),
        )
        .order_by(RetrievalRecord.created_at.desc(), RetrievalRecord.id.desc())
        .limit(KEEP_RECENT)
    )
    return (await session.execute(stmt)).scalars().all()
