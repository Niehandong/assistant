"""检索结果组装用的查询：检索单元（分段/子块）与分段+文档名。不做数据权限过滤（知识库访问由 ACL 在 service 层判定）。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.vector_store import UnitTable, unit_model
from app.models import ChildChunk, Document, Segment


@dataclass(frozen=True)
class UnitRow:
    id: int
    parent_id: int | None  # 子块所属父块；通用分段为 None
    position: int
    content: str


@dataclass(frozen=True)
class SegmentRow:
    id: int
    position: int
    segment_type: str
    content: str
    keywords: list[str]
    document_id: int
    document_name: str


async def load_units(
    session: AsyncSession, dataset_id: int, table: UnitTable, ids: Sequence[int]
) -> dict[int, UnitRow]:
    """候选单元（仍可检索的）。检索与组装之间被禁用/删除的单元自然消失。"""
    if not ids:
        return {}
    t = unit_model(table)
    if table == "child_chunk":
        stmt = select(ChildChunk.id, ChildChunk.segment_id, ChildChunk.position, ChildChunk.content)
    else:
        stmt = select(Segment.id, Segment.id, Segment.position, Segment.content)
    stmt = stmt.where(t.dataset_id == dataset_id, t.search_enabled.is_(True), t.id.in_(list(ids)))
    rows = (await session.execute(stmt)).all()
    return {int(r[0]): UnitRow(int(r[0]), int(r[1]) if table == "child_chunk" else None, int(r[2]), r[3]) for r in rows}


async def load_segments(session: AsyncSession, dataset_id: int, ids: Sequence[int]) -> dict[int, SegmentRow]:
    """返回结果用的通用分段/父块（含文档名）；已删除、已禁用、文档已删除的不返回。"""
    if not ids:
        return {}
    stmt = (
        select(
            Segment.id,
            Segment.position,
            Segment.segment_type,
            Segment.content,
            Segment.keywords,
            Segment.document_id,
            Document.name,
        )
        .join(Document, Document.id == Segment.document_id)
        .where(
            Segment.dataset_id == dataset_id,
            Segment.id.in_(list(ids)),
            Segment.is_deleted.is_(False),
            Segment.enabled.is_(True),
            Document.is_deleted.is_(False),
        )
    )
    rows = (await session.execute(stmt)).all()
    return {
        int(r[0]): SegmentRow(
            id=int(r[0]),
            position=int(r[1]),
            segment_type=r[2],
            content=r[3],
            keywords=list(r[4] or []) if r[2] == "general" else [],
            document_id=int(r[5]),
            document_name=r[6],
        )
        for r in rows
    }
