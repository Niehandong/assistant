"""知识库/文档统计冗余（tech-design-m2 3.2）。

两个函数都只在调用方的事务内执行 UPDATE，不 commit：
``recalc_document(session, document_id)`` 聚合本文档未删除的分段/子块；
``recalc_dataset(session, dataset_id)`` 聚合 document 表重算知识库冗余列。
调用时机：文档创建/删除/状态变化/启停、分段新增/删除/内容替换、重新分段。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer, cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DocStatus
from app.models import ChildChunk, Dataset, Document, Segment

PROCESSING_STATUSES = (DocStatus.QUEUED, DocStatus.PARSING, DocStatus.SPLITTING, DocStatus.INDEXING)


async def recalc_document(session: AsyncSession, document_id: int) -> None:
    """文档 char_count / segment_count（通用分段或父块，含禁用）/ child_count（当前代子块）。"""
    seg = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(Segment.char_count), 0)).where(
                Segment.document_id == document_id, Segment.is_deleted.is_(False)
            )
        )
    ).one()
    child_count = (
        await session.execute(
            select(func.count())
            .select_from(ChildChunk)
            .join(Segment, Segment.id == ChildChunk.segment_id)
            .where(
                ChildChunk.document_id == document_id,
                ChildChunk.is_deleted.is_(False),
                Segment.is_deleted.is_(False),
                ChildChunk.generation == Segment.child_generation,
            )
        )
    ).scalar_one()
    await session.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(segment_count=int(seg[0]), char_count=int(seg[1]), child_count=int(child_count))
    )


async def recalc_dataset(session: AsyncSession, dataset_id: int) -> None:
    """知识库冗余统计：文档数含处理中/失败；分段/字符仅统计可用文档。"""
    avail = Document.status == DocStatus.AVAILABLE
    row = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Document.status.in_(PROCESSING_STATUSES)),
                func.count().filter(Document.status == DocStatus.FAILED),
                func.count().filter(avail),
                cast(func.coalesce(func.sum(Document.segment_count).filter(avail), 0), Integer),
                cast(func.coalesce(func.sum(Document.child_count).filter(avail), 0), Integer),
                cast(func.coalesce(func.sum(Document.char_count).filter(avail), 0), BigInteger),
            ).where(Document.dataset_id == dataset_id, Document.is_deleted.is_(False))
        )
    ).one()
    await session.execute(
        update(Dataset)
        .where(Dataset.id == dataset_id)
        .values(
            doc_count=int(row[0]),
            processing_count=int(row[1]),
            failed_count=int(row[2]),
            available_doc_count=int(row[3]),
            segment_count=int(row[4]),
            child_segment_count=int(row[5]),
            char_count=int(row[6]),
        )
    )
