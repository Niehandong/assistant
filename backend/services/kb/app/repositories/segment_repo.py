"""分段/子块的批量写入与流水线查询（BE-18；列表/编辑类查询由 BE-19/20 追加）。

使用 Core 语句做批量写入：``insert ... returning`` 一次取回 id，tsv/向量用 executemany 更新。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Table, and_, bindparam, exists, func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.fulltext import tokens_param, tsv_expr
from app.models import ChildChunk, Segment
from app.repositories.dataset_repo import like_pattern
from app.splitters import SegmentDraft

BATCH = 500
_seg = cast(Table, Segment.__table__)
_child = cast(Table, ChildChunk.__table__)


async def soft_delete_units(session: AsyncSession, document_id: int, operator_id: int) -> None:
    """重新分段/重试分段阶段：软删除旧分段与子块（不可检索）。"""
    for table in (_child, _seg):
        await session.execute(
            update(table)
            .where(table.c.document_id == document_id, table.c.is_deleted.is_(False))
            .values(is_deleted=True, search_enabled=False, updated_by=operator_id)
        )


async def insert_drafts(
    session: AsyncSession,
    *,
    dataset_id: int,
    document_id: int,
    operator_id: int,
    drafts: Sequence[SegmentDraft],
    seg_tokens: Sequence[str],
    child_tokens: Sequence[Sequence[str]],
) -> int:
    """写入新分段（及子块），返回检索单元数（通用 = 分段数；父子 = 子块数）。

    ``seg_tokens`` / ``child_tokens`` 为与草稿同序的 jieba 分词文本，用于生成 tsv。
    父块自身不参与检索：无向量、无 tsv、索引状态直接为 indexed。
    """
    parent_child = any(d.children for d in drafts)
    seg_rows = [
        {
            "dataset_id": dataset_id,
            "document_id": document_id,
            "position": d.position,
            "segment_type": "parent" if parent_child else "general",
            "content": d.content,
            "char_count": d.char_count,
            "token_count": d.token_count,
            "index_status": "indexed" if parent_child else "pending",
            "created_by": operator_id,
            "updated_by": operator_id,
        }
        for d in drafts
    ]
    seg_ids: list[int] = []
    for i in range(0, len(seg_rows), BATCH):
        stmt = insert(_seg).returning(_seg.c.id, sort_by_parameter_order=True)
        seg_ids.extend(int(x) for x in (await session.execute(stmt, seg_rows[i : i + BATCH])).scalars().all())
    if not parent_child:
        await _update_tsv(session, _seg, list(zip(seg_ids, seg_tokens, strict=True)))
        return len(drafts)

    child_rows: list[dict[str, object]] = []
    child_tok: list[str] = []
    for sid, d, toks in zip(seg_ids, drafts, child_tokens, strict=True):
        for c, t in zip(d.children, toks, strict=True):
            child_rows.append(
                {
                    "dataset_id": dataset_id,
                    "document_id": document_id,
                    "segment_id": sid,
                    "generation": 1,
                    "position": c.position,
                    "content": c.content,
                    "char_count": c.char_count,
                    "token_count": c.token_count,
                    "index_status": "pending",
                    "created_by": operator_id,
                    "updated_by": operator_id,
                }
            )
            child_tok.append(t)
    child_ids: list[int] = []
    for i in range(0, len(child_rows), BATCH):
        stmt = insert(_child).returning(_child.c.id, sort_by_parameter_order=True)
        child_ids.extend(int(x) for x in (await session.execute(stmt, child_rows[i : i + BATCH])).scalars().all())
    await _update_tsv(session, _child, list(zip(child_ids, child_tok, strict=True)))
    return len(child_rows)


async def _update_tsv(session: AsyncSession, table: Table, pairs: list[tuple[int, str]]) -> None:
    stmt = update(table).where(table.c.id == bindparam("b_id")).values(tsv=tsv_expr(tokens_param()))
    for i in range(0, len(pairs), BATCH):
        params = [{"b_id": pid, "b_tokens": tok} for pid, tok in pairs[i : i + BATCH]]
        await session.execute(stmt, params)


async def has_live_units(session: AsyncSession, document_id: int) -> bool:
    for table in (_child, _seg):
        stmt = select(table.c.id).where(table.c.document_id == document_id, table.c.is_deleted.is_(False)).limit(1)
        if (await session.execute(stmt)).first() is not None:
            break
    else:
        return False
    return True


async def is_parent_child(session: AsyncSession, document_id: int) -> bool:
    stmt = select(_seg.c.id).where(
        _seg.c.document_id == document_id, _seg.c.is_deleted.is_(False), _seg.c.segment_type == "parent"
    )
    return (await session.execute(stmt.limit(1))).first() is not None


async def count_units(session: AsyncSession, document_id: int, *, child: bool) -> tuple[int, int]:
    """(检索单元总数, 已有向量的数量)；子块只统计当前代（父块未删除）。"""
    if child:
        stmt = (
            select(func.count(), func.count(_child.c.embedding))
            .select_from(_child.join(_seg, _seg.c.id == _child.c.segment_id))
            .where(
                _child.c.document_id == document_id,
                _child.c.is_deleted.is_(False),
                _seg.c.is_deleted.is_(False),
                _child.c.generation == _seg.c.child_generation,
            )
        )
    else:
        stmt = select(func.count(), func.count(_seg.c.embedding)).where(
            _seg.c.document_id == document_id, _seg.c.is_deleted.is_(False)
        )
    row = (await session.execute(stmt)).one()
    return int(row[0]), int(row[1])


async def pending_units(session: AsyncSession, document_id: int, *, child: bool, limit: int) -> list[tuple[int, str]]:
    """尚无向量的检索单元（按 id 升序）。"""
    if child:
        stmt = (
            select(_child.c.id, _child.c.content)
            .select_from(_child.join(_seg, _seg.c.id == _child.c.segment_id))
            .where(
                _child.c.document_id == document_id,
                _child.c.is_deleted.is_(False),
                _child.c.embedding.is_(None),
                _seg.c.is_deleted.is_(False),
                _child.c.generation == _seg.c.child_generation,
            )
            .order_by(_child.c.id)
            .limit(limit)
        )
    else:
        stmt = (
            select(_seg.c.id, _seg.c.content)
            .where(_seg.c.document_id == document_id, _seg.c.is_deleted.is_(False), _seg.c.embedding.is_(None))
            .order_by(_seg.c.id)
            .limit(limit)
        )
    return [(int(i), str(c)) for i, c in (await session.execute(stmt)).all()]


async def write_embeddings(
    session: AsyncSession, *, child: bool, items: Sequence[tuple[int, list[float]]], model_id: int
) -> None:
    """写入向量，同时写冗余列 ``embedding_model_id``（HNSW 部分索引的谓词，3.10.1）。"""
    table = _child if child else _seg
    stmt = (
        update(table)
        .where(table.c.id == bindparam("b_id"))
        .values(
            embedding=bindparam("b_emb", type_=HALFVEC()),
            embedding_model_id=model_id,
            index_status="indexed",
            index_error=None,
        )
    )
    await session.execute(stmt, [{"b_id": i, "b_emb": v} for i, v in items])


# ---------------------------------------------------------------- 分段管理（BE-20）


async def get_segment(
    session: AsyncSession, dataset_id: int, segment_id: int, *, for_update: bool = False
) -> Segment | None:
    stmt = select(Segment).where(
        Segment.id == segment_id, Segment.dataset_id == dataset_id, Segment.is_deleted.is_(False)
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)  # 加锁后以最新行为准
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_alive_segment(session: AsyncSession, segment_id: int) -> Segment | None:
    """按 id 取未删除分段（worker 用，不带知识库条件）。"""
    stmt = select(Segment).where(Segment.id == segment_id, Segment.is_deleted.is_(False))
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_alive_child(session: AsyncSession, child_id: int) -> ChildChunk | None:
    stmt = select(ChildChunk).where(ChildChunk.id == child_id, ChildChunk.is_deleted.is_(False))
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_child(
    session: AsyncSession, dataset_id: int, child_id: int, *, for_update: bool = False
) -> ChildChunk | None:
    stmt = select(ChildChunk).where(
        ChildChunk.id == child_id, ChildChunk.dataset_id == dataset_id, ChildChunk.is_deleted.is_(False)
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalar_one_or_none()


async def max_segment_position(session: AsyncSession, document_id: int) -> int:
    stmt = select(func.coalesce(func.max(Segment.position), 0)).where(
        Segment.document_id == document_id, Segment.is_deleted.is_(False)
    )
    return int((await session.execute(stmt)).scalar_one())


async def max_child_position(session: AsyncSession, segment_id: int, generation: int) -> int:
    stmt = select(func.coalesce(func.max(ChildChunk.position), 0)).where(
        ChildChunk.segment_id == segment_id, ChildChunk.generation == generation, ChildChunk.is_deleted.is_(False)
    )
    return int((await session.execute(stmt)).scalar_one())


async def list_segments(
    session: AsyncSession,
    document_id: int,
    *,
    keyword: str | None,
    enabled: bool | None,
    offset: int,
    limit: int,
) -> tuple[list[Segment], int, dict[int, list[ChildChunk]]]:
    """分页（按 position 升序）；父子时带出当前代子块（无 N+1）。keyword 匹配分段/父块或其子块（含待索引内容）。"""
    conds = [Segment.document_id == document_id, Segment.is_deleted.is_(False)]
    if enabled is not None:
        conds.append(Segment.enabled.is_(enabled))
    if keyword:
        pat = like_pattern(keyword)
        child_hit = exists().where(
            ChildChunk.segment_id == Segment.id,
            ChildChunk.generation == Segment.child_generation,
            ChildChunk.is_deleted.is_(False),
            or_(ChildChunk.content.like(pat, escape="\\"), ChildChunk.pending_content.like(pat, escape="\\")),
        )
        conds.append(
            or_(Segment.content.like(pat, escape="\\"), Segment.pending_content.like(pat, escape="\\"), child_hit)
        )
    total = int((await session.execute(select(func.count()).select_from(Segment).where(*conds))).scalar_one())
    segs = list(
        (
            await session.execute(
                select(Segment).where(*conds).order_by(Segment.position, Segment.id).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return segs, total, await children_of(session, [s.id for s in segs if s.segment_type == "parent"])


async def children_of(session: AsyncSession, segment_ids: Sequence[int]) -> dict[int, list[ChildChunk]]:
    result: dict[int, list[ChildChunk]] = {i: [] for i in segment_ids}
    if not segment_ids:
        return result
    stmt = (
        select(ChildChunk)
        .join(Segment, Segment.id == ChildChunk.segment_id)
        .where(
            ChildChunk.segment_id.in_(segment_ids),
            ChildChunk.is_deleted.is_(False),
            ChildChunk.generation == Segment.child_generation,
        )
        .order_by(ChildChunk.segment_id, ChildChunk.position, ChildChunk.id)
    )
    for c in (await session.execute(stmt)).scalars().all():
        result[c.segment_id].append(c)
    return result


async def soft_delete_segment(session: AsyncSession, segment_id: int, operator_id: int) -> None:
    """软删分段及其全部子块（含各代），并关闭检索可见标志。"""
    await session.execute(
        update(_child)
        .where(_child.c.segment_id == segment_id, _child.c.is_deleted.is_(False))
        .values(is_deleted=True, search_enabled=False, updated_by=operator_id)
    )
    await session.execute(
        update(_seg)
        .where(_seg.c.id == segment_id)
        .values(is_deleted=True, search_enabled=False, updated_by=operator_id)
    )


async def insert_children(
    session: AsyncSession,
    *,
    dataset_id: int,
    document_id: int,
    segment_id: int,
    generation: int,
    contents: Sequence[tuple[str, int]],
    tokens: Sequence[str],
    vectors: Sequence[list[float]],
    operator_id: int,
    model_id: int,
) -> None:
    """父块重建：写入新一代子块（含向量与 tsv，index_status=indexed）。``contents`` 为 (内容, token 数)。"""
    rows = [
        {
            "dataset_id": dataset_id,
            "document_id": document_id,
            "segment_id": segment_id,
            "generation": generation,
            "position": i,
            "content": text,
            "char_count": len(text),
            "token_count": n,
            "index_status": "pending",
            "created_by": operator_id,
            "updated_by": operator_id,
        }
        for i, (text, n) in enumerate(contents, start=1)
    ]
    if not rows:
        return
    ids = [
        int(x)
        for x in (await session.execute(insert(_child).returning(_child.c.id, sort_by_parameter_order=True), rows))
        .scalars()
        .all()
    ]
    await _update_tsv(session, _child, list(zip(ids, tokens, strict=True)))
    await write_embeddings(session, child=True, items=list(zip(ids, vectors, strict=True)), model_id=model_id)


async def soft_delete_old_children(
    session: AsyncSession, segment_id: int, keep_generation: int, operator_id: int
) -> None:
    await session.execute(
        update(_child)
        .where(
            and_(
                _child.c.segment_id == segment_id,
                _child.c.generation != keep_generation,
                _child.c.is_deleted.is_(False),
            )
        )
        .values(is_deleted=True, search_enabled=False, updated_by=operator_id)
    )
