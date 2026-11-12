"""分段/子块增量索引任务（tech-design-m2 3.6）：``segment.reindex``、``child.reindex``、``parent.regenerate``。

共同语义：
* 消息携带编辑后的 ``version``；换入前在同一事务内「锁知识库行 → 锁目标行」并确认 ``version`` 未变、
  目标未被删除，否则整体丢弃（更新的编辑会再投递新任务）；已是 ``indexed``（重复投递）也直接结束。
* 向量化在事务之外进行；检索在换入提交前一直使用旧内容与旧向量。
* 业务失败（模型停用/超时/维度不符）只把目标标记为 ``index_status=failed`` 并记录原因（旧内容继续生效），
  用户再次保存即重新入队；基础设施异常抛给消费者重试。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import SecretDecryptError, decrypt_secret
from app.engine.fulltext import tokenize, tokenize_keywords, tsv_expr
from app.model_clients.embedding import EmbeddingClient
from app.model_clients.errors import ModelClientError
from app.models import ChildChunk, Segment
from app.repositories import document_repo, model_repo, segment_repo
from app.schemas.process_rule import ProcessRule
from app.services import segment_service, stats_service
from app.splitters import count_tokens
from app.splitters.general import split_general
from app.worker import tasks_document
from platform_common.db import get_session_factory

logger = logging.getLogger("kb.worker.segment")

TASK_SEGMENT_REINDEX = "segment.reindex"
TASK_CHILD_REINDEX = "child.reindex"
TASK_PARENT_REGENERATE = "parent.regenerate"


class IndexFailed(Exception):
    """可读的业务失败原因（写入 ``index_error``，不超过 300 字）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message[:300]


@dataclass(frozen=True)
class _Model:
    base_url: str
    model_name: str
    api_key: str | None
    dimension: int | None
    id: int


async def _load_model(session: AsyncSession, model_id: int) -> _Model:
    settings = get_settings()
    model = await model_repo.get(session, model_id)
    if model is None or model.status != "enabled":
        raise IndexFailed("向量模型已停用")
    try:
        key = decrypt_secret(model.api_key_encrypted, settings) if model.api_key_encrypted else None
    except SecretDecryptError as exc:
        raise IndexFailed("向量模型调用失败：模型凭据无法解密") from exc
    return _Model(model.base_url, model.model_name, key, model.dimension, model.id)


async def _embed(model: _Model, texts: Sequence[str]) -> list[list[float]]:
    settings = get_settings()
    client = EmbeddingClient(
        model.base_url, model.model_name, model.api_key, timeout=settings.MODEL_HTTP_TIMEOUT_SECONDS
    )
    vectors: list[list[float]] = []
    step = max(1, settings.EMBED_BATCH_SIZE)
    for i in range(0, len(texts), step):
        try:
            vectors.extend(await client.embed(list(texts[i : i + step])))
        except ModelClientError as exc:
            raise IndexFailed(tasks_document._embed_failure(exc).message) from exc
    if len(vectors) != len(texts) or (model.dimension is not None and any(len(v) != model.dimension for v in vectors)):
        raise IndexFailed("向量维度与模型配置不一致")
    return vectors


# ---------------------------------------------------------------- segment.reindex


@dataclass(frozen=True)
class _Source:
    content: str
    keywords: list[str]
    model_id: int


async def _load_segment_source(session: AsyncSession, segment_id: int, version: int) -> _Source | None:
    seg = await segment_repo.get_alive_segment(session, segment_id)
    if seg is None or seg.version != version or seg.index_status == "indexed" or seg.segment_type != "general":
        return None
    dataset = await document_repo.get_dataset_alive(session, seg.dataset_id)
    if dataset is None or await document_repo.get_alive(session, seg.document_id) is None:
        return None
    content = seg.pending_content if seg.pending_content is not None else seg.content
    keywords = seg.pending_keywords if seg.pending_keywords is not None else seg.keywords
    return _Source(content, list(keywords or []), dataset.embedding_model_id)


async def _mark_failed(table: type[Segment] | type[ChildChunk], row_id: int, version: int, message: str) -> None:
    async with get_session_factory()() as s:
        await s.execute(
            update(table)
            .where(table.id == row_id, table.version == version, table.is_deleted.is_(False))
            .values(index_status="failed", index_error=message)
        )
        await s.commit()


async def handle_segment_reindex(envelope: dict[str, Any]) -> None:
    payload = envelope.get("payload") or {}
    segment_id, version = int(payload["segment_id"]), int(payload["version"])
    async with get_session_factory()() as s:
        source = await _load_segment_source(s, segment_id, version)
        if source is None:
            logger.info("分段索引任务已失效，忽略", extra={"segment_id": segment_id, "version": version})
            return
        try:
            model = await _load_model(s, source.model_id)
        except IndexFailed as exc:
            await s.rollback()
            await _mark_failed(Segment, segment_id, version, exc.message)
            return
    try:
        (vector,) = await _embed(model, [source.content])
    except IndexFailed as exc:
        await _mark_failed(Segment, segment_id, version, exc.message)
        return
    tokens = await asyncio.to_thread(tokenize, source.content)
    kw_tokens = await asyncio.to_thread(tokenize_keywords, source.keywords) if source.keywords else None
    token_count = await asyncio.to_thread(count_tokens, source.content)
    async with get_session_factory()() as s:
        seg = await _lock_segment_for_swap(s, segment_id, version)
        if seg is None:
            return
        dataset_id, document_id = seg.dataset_id, seg.document_id
        await s.execute(
            update(Segment)
            .where(Segment.id == segment_id)
            .values(
                content=source.content,
                keywords=source.keywords,
                char_count=len(source.content),
                token_count=token_count,
                pending_content=None,
                pending_keywords=None,
                embedding=vector,
                embedding_model_id=source.model_id,
                tsv=tsv_expr(tokens, kw_tokens),
                index_status="indexed",
                index_error=None,
            )
            .execution_options(synchronize_session=False)
        )
        await _finish_swap(s, dataset_id, document_id)


async def _lock_segment_for_swap(session: AsyncSession, segment_id: int, version: int) -> Segment | None:
    """换入前加锁（知识库 → 分段）并校验；不满足返回 None（调用方直接丢弃）。"""
    seg = await segment_repo.get_alive_segment(session, segment_id)
    if seg is None or not await document_repo.lock_dataset_row(session, seg.dataset_id):
        return None
    seg = await segment_repo.get_segment(session, seg.dataset_id, segment_id, for_update=True)
    if seg is None or seg.version != version or seg.index_status == "indexed":
        return None
    if await document_repo.get_alive(session, seg.document_id) is None:
        return None
    return seg


async def _lock_child_for_swap(session: AsyncSession, child_id: int, version: int) -> ChildChunk | None:
    child = await segment_repo.get_alive_child(session, child_id)
    if child is None or not await document_repo.lock_dataset_row(session, child.dataset_id):
        return None
    child = await segment_repo.get_child(session, child.dataset_id, child_id, for_update=True)
    if child is None or child.version != version or child.index_status == "indexed":
        return None
    parent = await segment_repo.get_segment(session, child.dataset_id, child.segment_id, for_update=True)
    if parent is None or parent.child_generation != child.generation:
        return None
    return child


async def _finish_swap(session: AsyncSession, dataset_id: int, document_id: int) -> None:
    await session.flush()
    await segment_service.refresh_search_flags(session, document_id)
    await stats_service.recalc_document(session, document_id)
    await stats_service.recalc_dataset(session, dataset_id)
    await session.commit()


# ---------------------------------------------------------------- child.reindex


async def handle_child_reindex(envelope: dict[str, Any]) -> None:
    payload = envelope.get("payload") or {}
    child_id, version = int(payload["child_id"]), int(payload["version"])
    async with get_session_factory()() as s:
        child = await segment_repo.get_alive_child(s, child_id)
        if child is None or child.version != version or child.index_status == "indexed":
            logger.info("子块索引任务已失效，忽略", extra={"child_id": child_id, "version": version})
            return
        parent = await segment_repo.get_segment(s, child.dataset_id, child.segment_id)
        dataset = await document_repo.get_dataset_alive(s, child.dataset_id)
        if parent is None or parent.child_generation != child.generation or dataset is None:
            return
        content = child.pending_content if child.pending_content is not None else child.content
        try:
            model = await _load_model(s, dataset.embedding_model_id)
        except IndexFailed as exc:
            await s.rollback()
            await _mark_failed(ChildChunk, child_id, version, exc.message)
            return
    try:
        (vector,) = await _embed(model, [content])
    except IndexFailed as exc:
        await _mark_failed(ChildChunk, child_id, version, exc.message)
        return
    tokens = await asyncio.to_thread(tokenize, content)
    token_count = await asyncio.to_thread(count_tokens, content)
    async with get_session_factory()() as s:
        locked = await _lock_child_for_swap(s, child_id, version)
        if locked is None:
            return
        dataset_id, document_id = locked.dataset_id, locked.document_id
        await s.execute(
            update(ChildChunk)
            .where(ChildChunk.id == child_id)
            .values(
                content=content,
                char_count=len(content),
                token_count=token_count,
                pending_content=None,
                embedding=vector,
                embedding_model_id=model.id,
                tsv=tsv_expr(tokens),
                index_status="indexed",
                index_error=None,
            )
            .execution_options(synchronize_session=False)
        )
        await _finish_swap(s, dataset_id, document_id)


# ---------------------------------------------------------------- parent.regenerate


async def handle_parent_regenerate(envelope: dict[str, Any]) -> None:
    payload = envelope.get("payload") or {}
    segment_id, version = int(payload["segment_id"]), int(payload["version"])
    async with get_session_factory()() as s:
        parent = await segment_repo.get_alive_segment(s, segment_id)
        if (
            parent is None
            or parent.version != version
            or parent.segment_type != "parent"
            or parent.pending_content is None
        ):
            logger.info("父块重建任务已失效，忽略", extra={"segment_id": segment_id, "version": version})
            return
        doc = await document_repo.get_alive(s, parent.document_id)
        dataset = await document_repo.get_dataset_alive(s, parent.dataset_id)
        if doc is None or dataset is None:
            return
        content = parent.pending_content
        rule = ProcessRule.model_validate(doc.process_rule)
        assert rule.child is not None
        child_rule = rule.child
        try:
            model = await _load_model(s, dataset.embedding_model_id)
        except IndexFailed as exc:
            await s.rollback()
            await _mark_failed(Segment, segment_id, version, exc.message)
            return
    parts = await asyncio.to_thread(split_general, content, child_rule.separator, child_rule.max_tokens, 0)
    if not parts:
        parts = [content]
    try:
        vectors = await _embed(model, parts)
    except IndexFailed as exc:
        await _mark_failed(Segment, segment_id, version, exc.message)
        return
    tokens = [await asyncio.to_thread(tokenize, p) for p in parts]
    counts = [await asyncio.to_thread(count_tokens, p) for p in parts]
    parent_tokens = await asyncio.to_thread(count_tokens, content)
    async with get_session_factory()() as s:
        locked = await _lock_segment_for_swap(s, segment_id, version)
        if locked is None:
            return
        dataset_id, document_id, operator = locked.dataset_id, locked.document_id, locked.updated_by or 0
        new_generation = locked.child_generation + 1
        await segment_repo.insert_children(
            s,
            dataset_id=dataset_id,
            document_id=document_id,
            segment_id=segment_id,
            generation=new_generation,
            contents=list(zip(parts, counts, strict=True)),
            tokens=tokens,
            vectors=vectors,
            operator_id=operator,
            model_id=model.id,
        )
        await segment_repo.soft_delete_old_children(s, segment_id, new_generation, operator)
        await s.execute(
            update(Segment)
            .where(Segment.id == segment_id)
            .values(
                content=content,
                char_count=len(content),
                token_count=parent_tokens,
                pending_content=None,
                child_generation=new_generation,
                index_status="indexed",
                index_error=None,
            )
            .execution_options(synchronize_session=False)
        )
        await _finish_swap(s, dataset_id, document_id)


TASK_HANDLERS = tasks_document.TASK_HANDLERS
TASK_HANDLERS[TASK_SEGMENT_REINDEX] = handle_segment_reindex
TASK_HANDLERS[TASK_CHILD_REINDEX] = handle_child_reindex
TASK_HANDLERS[TASK_PARENT_REGENERATE] = handle_parent_regenerate
