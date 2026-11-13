"""分段检索可见标志（BE-18）与分段/子块编辑（BE-20，tech-design-m2 3.3、5.6）。

写操作统一：``require_dataset(..., "edit", for_update=True)`` 锁知识库行 → 锁目标分段/子块行 → 校验所属文档为
``available``（否则 409504）。编辑只写 ``pending_*`` 与 ``index_status=updating``，检索继续使用旧内容；
提交后投递 ``segment.reindex`` / ``child.reindex`` / ``parent.regenerate``，由 worker 向量化后换入。
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import Request
from sqlalchemy import and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import TASK_STREAM, DocStatus
from app.models import ChildChunk, Document, Segment
from app.repositories import document_repo, segment_repo
from app.repositories.dataset_acl import require_dataset
from app.schemas.process_rule import FULL_DOC_MAX_TOKENS, ProcessRule
from app.schemas.segment import (
    ChildChunkItem,
    ChildCreate,
    ChildUpdate,
    SegmentCreate,
    SegmentItem,
    SegmentUpdate,
)
from app.services import stats_service
from app.splitters import count_tokens
from platform_common.auth.context import AuthContext
from platform_common.errors import BizError, CommonErrors
from platform_common.events.publisher import publish_after_commit
from platform_common.oplog import oplog_scope

ERR_DOC_BUSY = (409504, "文档处理中，暂不能执行该操作")
ERR_NOT_SUPPORTED = (400513, "当前分段方式不支持该操作")
ERR_CONFLICT = (409511, "该分段已被他人修改")
ERR_CONFIRM = (409512, "编辑父块将重新生成子块，请确认")
ERR_KEYWORDS = (400512, "关键词不合法（最多 10 个，每个不超过 20 字）")
MAX_KEYWORDS = 10
MAX_KEYWORD_LEN = 20
MAX_CONTENT_CHARS = 200_000  # 防止超大请求体占用分词资源，超出直接按超长处理


async def refresh_search_flags(session: AsyncSession, document_id: int) -> None:
    """按 3.3 重算该文档全部分段/子块的 ``search_enabled``；只执行 UPDATE、不 commit。

    * 通用分段：doc.enabled ∧ doc.status='available' ∧ seg.enabled ∧ ¬seg.is_deleted ∧ embedding 非空；
    * 子块：另需父块未删除且启用、子块代数 = 父块当前代数。
    * 父块自身不参与检索（无向量），恒为 false。
    只更新值发生变化的行，避免无谓的写放大。
    """
    doc_ok = and_(Document.enabled.is_(True), Document.status == "available", Document.is_deleted.is_(False))
    seg_flag = and_(
        doc_ok,
        Segment.segment_type == "general",
        Segment.enabled.is_(True),
        Segment.is_deleted.is_(False),
        Segment.embedding.is_not(None),
    )
    await session.execute(
        update(Segment)
        .where(Segment.document_id == Document.id, Segment.document_id == document_id)
        .where(Segment.search_enabled.is_distinct_from(seg_flag))
        .values(search_enabled=seg_flag)
        .execution_options(synchronize_session=False)
    )
    child_flag = and_(
        doc_ok,
        Segment.enabled.is_(True),
        Segment.is_deleted.is_(False),
        ChildChunk.is_deleted.is_(False),
        ChildChunk.embedding.is_not(None),
        ChildChunk.generation == Segment.child_generation,
    )
    await session.execute(
        update(ChildChunk)
        .where(
            ChildChunk.document_id == Document.id,
            ChildChunk.segment_id == Segment.id,
            ChildChunk.document_id == document_id,
        )
        .where(ChildChunk.search_enabled.is_distinct_from(child_flag))
        .values(search_enabled=child_flag)
        .execution_options(synchronize_session=False)
    )


# ---------------------------------------------------------------- 展示转换


def child_item(c: ChildChunk) -> ChildChunkItem:
    """子块展示：``updating``/``failed`` 且有待索引内容时显示用户编辑后的内容。"""
    content = c.pending_content if c.pending_content is not None else c.content
    return ChildChunkItem(
        id=c.id,
        position=c.position,
        content=content,
        char_count=len(content) if c.pending_content is not None else c.char_count,
        token_count=c.token_count,
        edited=c.edited,
        index_status=c.index_status,  # type: ignore[arg-type]
        index_error=c.index_error,
        version=c.version,
    )


def segment_item(s: Segment, children: list[ChildChunk]) -> SegmentItem:
    content = s.pending_content if s.pending_content is not None else s.content
    keywords = s.pending_keywords if s.pending_keywords is not None else s.keywords
    return SegmentItem(
        id=s.id,
        position=s.position,
        segment_type=s.segment_type,  # type: ignore[arg-type]
        content=content,
        keywords=list(keywords or []),
        char_count=len(content) if s.pending_content is not None else s.char_count,
        token_count=s.token_count,
        enabled=s.enabled,
        edited=s.edited,
        hit_count=s.hit_count,
        index_status=s.index_status,  # type: ignore[arg-type]
        index_error=s.index_error,
        version=s.version,
        children=[child_item(c) for c in children],
    )


# ---------------------------------------------------------------- 校验


async def _check_content(content: str, max_tokens: int) -> str:
    """1 ~ max_tokens tokens，否则 400511（data.max_tokens）。返回去除首尾空白的内容。"""
    text = content.strip()
    err = BizError(400511, "分段内容长度超出范围", {"max_tokens": max_tokens})
    if not text or len(text) > MAX_CONTENT_CHARS:
        raise err
    if await asyncio.to_thread(count_tokens, text) > max_tokens:
        raise err
    return text


def _check_keywords(keywords: list[str]) -> list[str]:
    cleaned: list[str] = []
    for k in keywords:
        k = k.strip()
        if not k or len(k) > MAX_KEYWORD_LEN:
            raise BizError(*ERR_KEYWORDS)
        if k not in cleaned:
            cleaned.append(k)
    if len(cleaned) > MAX_KEYWORDS:
        raise BizError(*ERR_KEYWORDS)
    return cleaned


def _rule(doc: Document) -> ProcessRule:
    return ProcessRule.model_validate(doc.process_rule)


def _general_limit(doc: Document) -> int:
    rule = _rule(doc)
    assert rule.general is not None
    return rule.general.max_tokens


def _parent_limit(doc: Document) -> int:
    rule = _rule(doc)
    assert rule.parent is not None
    return FULL_DOC_MAX_TOKENS if rule.parent.mode == "full_doc" else rule.parent.max_tokens


def _child_limit(doc: Document) -> int:
    rule = _rule(doc)
    assert rule.child is not None
    return rule.child.max_tokens


async def _alive_available_doc(session: AsyncSession, dataset_id: int, document_id: int) -> Document:
    doc = await document_repo.get_in_dataset(session, dataset_id, document_id)
    if doc is None:
        raise BizError(*CommonErrors.NOT_FOUND)
    if doc.status != DocStatus.AVAILABLE:
        raise BizError(*ERR_DOC_BUSY)
    return doc


async def _segment_for_write(session: AsyncSession, dataset_id: int, segment_id: int) -> tuple[Segment, Document]:
    seg = await segment_repo.get_segment(session, dataset_id, segment_id, for_update=True)
    if seg is None:
        raise BizError(*CommonErrors.NOT_FOUND)
    return seg, await _alive_available_doc(session, dataset_id, seg.document_id)


async def _child_for_write(
    session: AsyncSession, dataset_id: int, child_id: int
) -> tuple[ChildChunk, Segment, Document]:
    child = await segment_repo.get_child(session, dataset_id, child_id, for_update=True)
    if child is None:
        raise BizError(*CommonErrors.NOT_FOUND)
    parent = await segment_repo.get_segment(session, dataset_id, child.segment_id, for_update=True)
    if parent is None or parent.child_generation != child.generation:
        raise BizError(*CommonErrors.NOT_FOUND)
    return child, parent, await _alive_available_doc(session, dataset_id, child.document_id)


def _enqueue(session: AsyncSession, task_type: str, payload: dict[str, Any]) -> None:
    publish_after_commit(session, TASK_STREAM, task_type, payload)


# ---------------------------------------------------------------- 查询


async def list_segments(
    session: AsyncSession,
    ctx: AuthContext,
    dataset_id: int,
    document_id: int,
    *,
    keyword: str | None,
    enabled: bool | None,
    offset: int,
    limit: int,
) -> tuple[list[SegmentItem], int]:
    await require_dataset(session, ctx, dataset_id, "read")
    return await list_segments_unchecked(
        session, dataset_id, document_id, keyword=keyword, enabled=enabled, offset=offset, limit=limit
    )


async def list_segments_unchecked(
    session: AsyncSession,
    dataset_id: int,
    document_id: int,
    *,
    keyword: str | None,
    enabled: bool | None,
    offset: int,
    limit: int,
) -> tuple[list[SegmentItem], int]:
    """不校验 ACL：调用方（管理视图）已按其自身规则确认可见性；文档须属于该知识库。"""
    if await document_repo.get_in_dataset(session, dataset_id, document_id) is None:
        raise BizError(*CommonErrors.NOT_FOUND)
    segs, total, children = await segment_repo.list_segments(
        session, document_id, keyword=keyword, enabled=enabled, offset=offset, limit=limit
    )
    return [segment_item(s, children.get(s.id, [])) for s in segs], total


# ---------------------------------------------------------------- 分段写操作


async def create_segment(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, document_id: int, body: SegmentCreate
) -> SegmentItem:
    async with oplog_scope(
        request, ctx, module="segment", action="create", target_type="document", target_id=document_id
    ) as h:
        dataset = await require_dataset(session, ctx, dataset_id, "edit", for_update=True)
        doc = await document_repo.get_in_dataset(session, dataset.id, document_id, for_update=True)
        if doc is None:
            raise BizError(*CommonErrors.NOT_FOUND)
        h.set_target(doc.id, doc.name)
        if doc.chunk_mode != "general":
            raise BizError(*ERR_NOT_SUPPORTED)
        if doc.status != DocStatus.AVAILABLE:
            raise BizError(*ERR_DOC_BUSY)
        content = await _check_content(body.content, _general_limit(doc))
        keywords = _check_keywords(body.keywords)
        seg = Segment(
            dataset_id=dataset.id,
            document_id=doc.id,
            position=await segment_repo.max_segment_position(session, doc.id) + 1,
            segment_type="general",
            content=content,
            keywords=keywords,
            char_count=len(content),
            token_count=await asyncio.to_thread(count_tokens, content),
            edited=True,
            index_status="pending",
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
        )
        session.add(seg)
        await session.flush()
        await stats_service.recalc_document(session, doc.id)
        await stats_service.recalc_dataset(session, dataset.id)
        _enqueue(session, "segment.reindex", {"segment_id": seg.id, "version": seg.version})
        item = segment_item(seg, [])
        h.summary = {"dataset_id": dataset.id, "segment_id": seg.id, "position": seg.position, "chars": len(content)}
        await session.commit()
        return item


async def update_segment(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, segment_id: int, body: SegmentUpdate
) -> SegmentItem:
    async with oplog_scope(
        request, ctx, module="segment", action="update", target_type="segment", target_id=segment_id
    ) as h:
        dataset = await require_dataset(session, ctx, dataset_id, "edit", for_update=True)
        seg, doc = await _segment_for_write(session, dataset.id, segment_id)
        h.set_target(seg.id, f"{doc.name}#{seg.position}")
        if seg.version != body.version:
            raise BizError(*ERR_CONFLICT)
        is_parent = seg.segment_type == "parent"
        if is_parent and not body.confirm_regenerate_children:
            raise BizError(*ERR_CONFIRM)
        content = await _check_content(body.content, _parent_limit(doc) if is_parent else _general_limit(doc))
        before_len = seg.char_count
        seg.pending_content = content
        # 父子分段不维护关键词（忽略入参）；通用分段未传 keywords 则沿用当前关键词
        seg.pending_keywords = None if is_parent or body.keywords is None else _check_keywords(body.keywords)
        seg.index_status = "updating"
        seg.index_error = None
        seg.edited = True
        seg.version += 1
        seg.updated_by = ctx.user_id
        await session.flush()
        _enqueue(
            session,
            "parent.regenerate" if is_parent else "segment.reindex",
            {"segment_id": seg.id, "version": seg.version},
        )
        h.summary = {
            "dataset_id": dataset.id,
            "document_id": doc.id,
            "position": seg.position,
            "before_chars": before_len,
            "after_chars": len(content),
        }
        item = segment_item(seg, await _live_children(session, seg))
        await session.commit()
        return item


async def _live_children(session: AsyncSession, seg: Segment) -> list[ChildChunk]:
    if seg.segment_type != "parent":
        return []
    return (await segment_repo.children_of(session, [seg.id])).get(seg.id, [])


async def set_segment_enabled(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, segment_id: int, enabled: bool
) -> SegmentItem:
    async with oplog_scope(
        request,
        ctx,
        module="segment",
        action="enable" if enabled else "disable",
        target_type="segment",
        target_id=segment_id,
    ) as h:
        dataset = await require_dataset(session, ctx, dataset_id, "edit", for_update=True)
        seg, doc = await _segment_for_write(session, dataset.id, segment_id)
        h.set_target(seg.id, f"{doc.name}#{seg.position}")
        if seg.enabled != enabled:
            seg.enabled = enabled
            seg.updated_by = ctx.user_id
            await session.flush()
            await refresh_search_flags(session, doc.id)
        h.summary = {"dataset_id": dataset.id, "document_id": doc.id, "enabled": enabled}
        item = segment_item(seg, await _live_children(session, seg))
        await session.commit()
        return item


async def delete_segment(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, segment_id: int
) -> None:
    async with oplog_scope(
        request, ctx, module="segment", action="delete", target_type="segment", target_id=segment_id
    ) as h:
        dataset = await require_dataset(session, ctx, dataset_id, "edit", for_update=True)
        seg, doc = await _segment_for_write(session, dataset.id, segment_id)
        h.set_target(seg.id, f"{doc.name}#{seg.position}")
        await segment_repo.soft_delete_segment(session, seg.id, ctx.user_id)
        await session.flush()
        await stats_service.recalc_document(session, doc.id)
        await stats_service.recalc_dataset(session, dataset.id)
        h.summary = {"dataset_id": dataset.id, "document_id": doc.id, "position": seg.position}
        await session.commit()


# ---------------------------------------------------------------- 子块写操作


def _require_parent_stable(parent: Segment) -> None:
    """父块正在按新内容重建子块时，子块的新增/编辑会随旧代子块一起被替换，直接拒绝。"""
    if parent.index_status == "updating":
        raise BizError(*ERR_CONFLICT)


async def create_child(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, segment_id: int, body: ChildCreate
) -> ChildChunkItem:
    async with oplog_scope(
        request, ctx, module="segment", action="child_create", target_type="segment", target_id=segment_id
    ) as h:
        dataset = await require_dataset(session, ctx, dataset_id, "edit", for_update=True)
        parent, doc = await _segment_for_write(session, dataset.id, segment_id)
        h.set_target(parent.id, f"{doc.name}#{parent.position}")
        if parent.segment_type != "parent":
            raise BizError(*ERR_NOT_SUPPORTED)
        _require_parent_stable(parent)
        content = await _check_content(body.content, _child_limit(doc))
        child = ChildChunk(
            dataset_id=dataset.id,
            document_id=doc.id,
            segment_id=parent.id,
            generation=parent.child_generation,
            position=await segment_repo.max_child_position(session, parent.id, parent.child_generation) + 1,
            content=content,
            char_count=len(content),
            token_count=await asyncio.to_thread(count_tokens, content),
            edited=True,
            index_status="pending",
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
        )
        session.add(child)
        await session.flush()
        await stats_service.recalc_document(session, doc.id)
        _enqueue(session, "child.reindex", {"child_id": child.id, "version": child.version})
        h.summary = {"dataset_id": dataset.id, "child_id": child.id, "chars": len(content)}
        item = child_item(child)
        await session.commit()
        return item


async def update_child(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, child_id: int, body: ChildUpdate
) -> ChildChunkItem:
    async with oplog_scope(
        request, ctx, module="segment", action="child_update", target_type="child_chunk", target_id=child_id
    ) as h:
        dataset = await require_dataset(session, ctx, dataset_id, "edit", for_update=True)
        child, parent, doc = await _child_for_write(session, dataset.id, child_id)
        h.set_target(child.id, f"{doc.name}#{parent.position}.{child.position}")
        _require_parent_stable(parent)
        if child.version != body.version:
            raise BizError(*ERR_CONFLICT)
        content = await _check_content(body.content, _child_limit(doc))
        child.pending_content = content
        child.index_status = "updating"
        child.index_error = None
        child.edited = True
        child.version += 1
        child.updated_by = ctx.user_id
        await session.flush()
        _enqueue(session, "child.reindex", {"child_id": child.id, "version": child.version})
        h.summary = {"dataset_id": dataset.id, "document_id": doc.id, "after_chars": len(content)}
        item = child_item(child)
        await session.commit()
        return item


async def delete_child(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, child_id: int
) -> None:
    async with oplog_scope(
        request, ctx, module="segment", action="child_delete", target_type="child_chunk", target_id=child_id
    ) as h:
        dataset = await require_dataset(session, ctx, dataset_id, "edit", for_update=True)
        child, parent, doc = await _child_for_write(session, dataset.id, child_id)
        h.set_target(child.id, f"{doc.name}#{parent.position}.{child.position}")
        child.is_deleted = True
        child.search_enabled = False
        child.updated_by = ctx.user_id
        await session.flush()
        await refresh_search_flags(session, doc.id)
        await stats_service.recalc_document(session, doc.id)
        await stats_service.recalc_dataset(session, dataset.id)
        h.summary = {"dataset_id": dataset.id, "document_id": doc.id}
        await session.commit()
