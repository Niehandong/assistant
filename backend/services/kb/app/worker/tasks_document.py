"""文档处理流水线（tech-design-m2 3.6）：解析 → 分段 → 向量化 → 完成。

并发与幂等：
* 消息 ``document.process`` 至少投递一次；每个阶段的状态写入都带 ``process_attempt`` 栅栏（见 document_repo），
  文档被删除、知识库被删除、重试/重新分段/超时巡检使 attempt 变化后，旧任务在下一次状态写入时静默结束。
* 单文档单 attempt 的处理由 Redis 锁（``SET NX EX`` + 心跳续期）串行，重复投递/XAUTOCLAIM 接管不会并发处理。
* 分段阶段在同一事务内「锁文档行、校验栅栏 → 软删旧分段 → 写新分段」；
  向量化按批提交，只处理向量为空的单元，可从中断处续做。
* 完成/失败时先锁知识库行再重算统计，保证并发完成的文档统计不互相覆盖。
* 业务失败（可读原因）直接把文档置为 failed 并正常结束；仅基础设施异常（DB/Redis/对象存储）向上抛出，由消费者重试。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import SecretDecryptError, decrypt_secret
from app.engine.fulltext import tokenize
from app.model_clients.embedding import EmbeddingClient
from app.model_clients.errors import ModelBadResponse, ModelClientError, ModelHTTPError, ModelTimeout
from app.parsers import ProcessError, parse_with_timeout
from app.parsers.registry import get_pool, shutdown_pool
from app.repositories import document_repo, model_repo, segment_repo
from app.schemas.process_rule import ProcessRule
from app.services import segment_service, stats_service
from app.splitters import SegmentDraft, split_document
from app.storage.s3 import ObjectNotFound, get_storage
from platform_common.db import get_session_factory
from platform_common.redis import get_redis

logger = logging.getLogger("kb.worker.document")

STAGES = ("parse", "split", "index")
TASK_DOCUMENT_PROCESS = "document.process"
INFRA_ERRORS: tuple[type[BaseException], ...] = (BotoCoreError, ClientError, RedisError, DBAPIError, PoolTimeoutError)

Handler = Callable[[dict[str, Any]], Awaitable[None]]
# BE-20 等任务类型在此注册；未注册的类型忽略并告警
TASK_HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[None]]] = {}

_RELEASE_LUA = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0"
_RENEW_LUA = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) end return 0"
_split_gate = asyncio.Semaphore(2)  # 分段/分词是 CPU 密集的纯 Python，限制同时进行的数量


class Fenced(Exception):
    """栅栏不一致（已删除/attempt 变化/状态已变）：静默结束。"""


@dataclass
class StageFailure(Exception):
    stage: str
    code: str
    message: str


@dataclass
class DocCtx:
    document_id: int
    attempt: int
    dataset_id: int
    upload_file_id: int
    ext: str
    storage_key: str
    rule: dict[str, Any]
    created_by: int
    model_id: int
    status: str

    @property
    def parsed_key(self) -> str:
        return f"parsed/{self.upload_file_id}.txt"


# ---------------------------------------------------------------- 入口


async def handle_task(envelope: dict[str, Any]) -> None:
    """``StreamConsumer`` 的 handler：按 type 分发。"""
    type_ = str(envelope.get("type", ""))
    payload = envelope.get("payload") or {}
    if type_ == TASK_DOCUMENT_PROCESS:
        await process_document(
            int(payload["document_id"]), int(payload["attempt"]), str(payload.get("from_stage") or "parse")
        )
        return
    handler = TASK_HANDLERS.get(type_)
    if handler is None:
        logger.warning("未知任务类型，已忽略", extra={"type": type_})
        return
    await handler(envelope)


async def process_document(document_id: int, attempt: int, from_stage: str = "parse") -> None:
    settings = get_settings()
    if from_stage not in STAGES:
        from_stage = "parse"
    key = f"kb:doc:process:{document_id}:{attempt}"
    token = uuid.uuid4().hex
    redis = get_redis()
    if not await redis.set(key, token, nx=True, ex=settings.DOC_LOCK_TTL_SECONDS):
        logger.info("文档正在被处理（重复投递），忽略", extra={"document_id": document_id, "attempt": attempt})
        return
    beat = asyncio.create_task(_heartbeat(key, token, settings.DOC_LOCK_TTL_SECONDS))
    try:
        await _run(settings, document_id, attempt, from_stage)
    finally:
        beat.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await beat
        with contextlib.suppress(Exception):
            await redis.eval(_RELEASE_LUA, 1, key, token)


async def _heartbeat(key: str, token: str, ttl: int) -> None:
    redis = get_redis()
    while True:
        await asyncio.sleep(max(1.0, ttl / 3))
        try:
            await redis.eval(_RENEW_LUA, 1, key, token, ttl)
        except Exception:
            logger.warning("文档处理锁续期失败", exc_info=True)


async def _load_ctx(document_id: int, attempt: int) -> DocCtx | None:
    async with get_session_factory()() as s:
        doc = await document_repo.get_alive(s, document_id)
        if doc is None or doc.process_attempt != attempt or doc.status not in document_repo.PROCESSING_STATUSES:
            return None
        dataset = await document_repo.get_dataset_alive(s, doc.dataset_id)
        if dataset is None:
            return None
        return DocCtx(
            document_id=doc.id,
            attempt=attempt,
            dataset_id=doc.dataset_id,
            upload_file_id=doc.upload_file_id,
            ext=doc.file_ext,
            storage_key=doc.storage_key,
            rule=dict(doc.process_rule),
            created_by=doc.created_by,
            model_id=dataset.embedding_model_id,
            status=doc.status,
        )


def _start_index(ctx: DocCtx, from_stage: str) -> int:
    """重试/重新分段按 from_stage；崩溃后被接管（状态已在某阶段中）则从该阶段继续，不早于 from_stage。"""
    base = STAGES.index(from_stage)
    if ctx.status == "queued":
        return base
    return max(base, STAGES.index(document_repo.STAGE_OF_STATUS[ctx.status]))


async def _run(settings: Settings, document_id: int, attempt: int, from_stage: str) -> None:
    ctx = await _load_ctx(document_id, attempt)
    if ctx is None:
        logger.info("任务已失效，忽略", extra={"document_id": document_id, "attempt": attempt})
        return
    start = _start_index(ctx, from_stage)
    stage = STAGES[start]
    try:
        storage = get_storage()
        if start > 0 and not await storage.exists(ctx.parsed_key):
            start = 0  # 解析文本缺失：回到解析阶段
        if start == 2:
            async with get_session_factory()() as s:
                if not await segment_repo.has_live_units(s, ctx.document_id):
                    start = 1  # 没有分段（异常中断）：回到分段阶段
        if start == 0:
            stage = "parse"
            await _stage_parse(ctx, settings)
        if start <= 1:
            stage = "split"
            await _stage_split(ctx)
        stage = "index"
        await _stage_index(ctx, settings)
        await _finish(ctx)
        logger.info("文档处理完成", extra={"document_id": document_id, "attempt": attempt})
    except Fenced:
        logger.info("任务已被取消或失效，静默结束", extra={"document_id": document_id, "attempt": attempt})
    except StageFailure as f:
        await _fail(ctx, f)
    except INFRA_ERRORS:
        raise  # 基础设施异常：不改文档状态，交给消费者重试（超时巡检兜底）
    except Exception:
        logger.exception("文档处理异常", extra={"document_id": document_id, "stage": stage})
        generic = {
            "parse": ("PARSE_ERROR", "文件解析失败：内部错误"),
            "split": ("SPLIT_ERROR", "分段失败：内部错误"),
            "index": ("EMBEDDING_ERROR", "向量化失败：内部错误"),
        }[stage]
        await _fail(ctx, StageFailure(stage, *generic))


# ---------------------------------------------------------------- 阶段：解析


async def _enter(session: AsyncSession, ctx: DocCtx, status: str) -> None:
    if not await document_repo.cas_status(session, ctx.document_id, ctx.attempt, status):
        raise Fenced
    await session.commit()


async def _stage_parse(ctx: DocCtx, settings: Settings) -> None:
    async with get_session_factory()() as s:
        await _enter(s, ctx, "parsing")
    storage = get_storage()
    if not await storage.exists(ctx.parsed_key):
        try:
            raw = await storage.get_bytes(ctx.storage_key)
        except ObjectNotFound as exc:
            raise StageFailure("parse", "FILE_MISSING", "原文件不存在，请重新上传") from exc
        text = await _parse_bytes(raw, ctx.ext, settings)
        await storage.put_bytes(ctx.parsed_key, text.encode("utf-8"), "text/plain; charset=utf-8")
    async with get_session_factory()() as s:
        if not await document_repo.cas_parsed_key(s, ctx.document_id, ctx.attempt, ctx.parsed_key):
            raise Fenced
        await s.commit()


async def _parse_bytes(raw: bytes, ext: str, settings: Settings) -> str:
    fd, name = tempfile.mkstemp(prefix="kb-parse-", suffix=f".{ext}")
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            await asyncio.to_thread(out.write, raw)
        return await parse_with_timeout(
            path, ext, settings.PARSE_TIMEOUT_SECONDS, pool=get_pool(settings.PARSE_PROCESS_WORKERS)
        )
    except ProcessError as exc:
        if exc.reason == "NO_TEXT":
            raise StageFailure("parse", "NO_TEXT", "文件无可提取文本") from exc
        raise StageFailure("parse", "PARSE_ERROR", f"文件解析失败：{exc.message}") from exc
    except BrokenProcessPool as exc:
        shutdown_pool()
        raise StageFailure("parse", "PARSE_ERROR", "文件解析失败：文件已加密或已损坏") from exc
    finally:
        await asyncio.to_thread(path.unlink, missing_ok=True)


# ---------------------------------------------------------------- 阶段：分段


def _tokenize_drafts(drafts: list[SegmentDraft]) -> tuple[list[str], list[list[str]]]:
    if any(d.children for d in drafts):
        return [], [[tokenize(c.content) for c in d.children] for d in drafts]
    return [tokenize(d.content) for d in drafts], []


async def _stage_split(ctx: DocCtx) -> None:
    async with get_session_factory()() as s:
        await _enter(s, ctx, "splitting")
        model = await model_repo.get(s, ctx.model_id)
        model_max = model.max_input_tokens if model is not None else None
    try:
        raw = await get_storage().get_bytes(ctx.parsed_key)
    except ObjectNotFound as exc:
        raise StageFailure("split", "SPLIT_ERROR", "分段失败：解析文本不存在，请重试") from exc
    text = raw.decode("utf-8")
    try:
        rule = ProcessRule.model_validate(ctx.rule)
    except ValidationError as exc:
        raise StageFailure("split", "SPLIT_ERROR", "分段失败：分段规则不合法") from exc
    async with _split_gate:
        try:
            drafts = await asyncio.to_thread(split_document, text, rule, model_max)
        except ProcessError as exc:
            if exc.reason == "FULL_DOC_TOO_LONG":
                raise StageFailure("split", "FULL_DOC_TOO_LONG", "文档超过 10,000 tokens，请使用段落模式") from exc
            if exc.reason == "NO_TEXT":
                raise StageFailure("split", "NO_TEXT", "文件无可提取文本") from exc
            detail = exc.message
            if exc.reason == "INVALID_RULE" and isinstance(exc.data, dict) and exc.data.get("errors"):
                detail = str(exc.data["errors"][0].get("message", detail))
            raise StageFailure("split", "SPLIT_ERROR", f"分段失败：{detail}") from exc
        seg_tokens, child_tokens = await asyncio.to_thread(_tokenize_drafts, drafts)
    async with get_session_factory()() as s:
        # 锁文档行并校验栅栏，与「处理中删除」串行
        doc = await document_repo.get_alive(s, ctx.document_id, for_update=True)
        if doc is None or doc.process_attempt != ctx.attempt or doc.status != "splitting":
            raise Fenced
        await segment_repo.soft_delete_units(s, ctx.document_id, ctx.created_by)
        total = await segment_repo.insert_drafts(
            s,
            dataset_id=ctx.dataset_id,
            document_id=ctx.document_id,
            operator_id=ctx.created_by,
            drafts=drafts,
            seg_tokens=seg_tokens,
            child_tokens=child_tokens,
        )
        if not await document_repo.cas_progress(s, ctx.document_id, ctx.attempt, done=0, total=total):
            raise Fenced
        await stats_service.recalc_document(s, ctx.document_id)
        await s.commit()


# ---------------------------------------------------------------- 阶段：向量化


def _embed_failure(exc: ModelClientError) -> StageFailure:
    if isinstance(exc, ModelTimeout):
        return StageFailure("index", "EMBEDDING_TIMEOUT", "向量模型调用超时")
    if isinstance(exc, ModelHTTPError):
        return StageFailure("index", "EMBEDDING_ERROR", f"向量模型调用失败：{exc}")
    if isinstance(exc, ModelBadResponse):
        return StageFailure("index", "EMBEDDING_ERROR", f"向量模型调用失败：{exc}")
    return StageFailure("index", "EMBEDDING_ERROR", "向量模型调用失败")


async def _stage_index(ctx: DocCtx, settings: Settings) -> None:
    async with get_session_factory()() as s:
        await _enter(s, ctx, "indexing")
        child = await segment_repo.is_parent_child(s, ctx.document_id)
        total, done = await segment_repo.count_units(s, ctx.document_id, child=child)
        if not await document_repo.cas_progress(s, ctx.document_id, ctx.attempt, done=done, total=total):
            raise Fenced
        await s.commit()
    while True:
        async with get_session_factory()() as s:
            model = await model_repo.get(s, ctx.model_id)
            if model is None or model.status != "enabled":
                raise StageFailure("index", "EMBEDDING_DISABLED", "向量模型已停用")
            units = await segment_repo.pending_units(s, ctx.document_id, child=child, limit=settings.EMBED_BATCH_SIZE)
            base_url, model_name, dimension = model.base_url, model.model_name, model.dimension
            try:
                api_key = decrypt_secret(model.api_key_encrypted, settings) if model.api_key_encrypted else None
            except SecretDecryptError as exc:
                raise StageFailure("index", "EMBEDDING_ERROR", "向量模型调用失败：模型凭据无法解密") from exc
        if not units:
            return
        client = EmbeddingClient(base_url, model_name, api_key, timeout=settings.MODEL_HTTP_TIMEOUT_SECONDS)
        try:
            vectors = await client.embed([content for _, content in units])
        except ModelClientError as exc:
            raise _embed_failure(exc) from exc
        if dimension is not None and any(len(v) != dimension for v in vectors):
            raise StageFailure("index", "DIMENSION_MISMATCH", "向量维度与模型配置不一致")
        done += len(units)
        async with get_session_factory()() as s:
            # 先过栅栏再写向量：文档被删除/失效则整批丢弃
            if not await document_repo.cas_progress(s, ctx.document_id, ctx.attempt, done=done):
                raise Fenced
            await segment_repo.write_embeddings(
                s,
                child=child,
                items=[(uid, vec) for (uid, _), vec in zip(units, vectors, strict=True)],
                model_id=ctx.model_id,
            )
            await s.commit()


# ---------------------------------------------------------------- 完成 / 失败


async def _finish(ctx: DocCtx) -> None:
    async with get_session_factory()() as s:
        if not await document_repo.lock_dataset_row(s, ctx.dataset_id):
            raise Fenced
        doc = await document_repo.get_alive(s, ctx.document_id, for_update=True)
        if doc is None or doc.process_attempt != ctx.attempt or doc.status != "indexing":
            raise Fenced
        child = await segment_repo.is_parent_child(s, ctx.document_id)
        total, embedded = await segment_repo.count_units(s, ctx.document_id, child=child)
        if embedded < total:
            raise StageFailure("index", "EMBEDDING_ERROR", "向量模型调用失败：部分分段未完成向量化")
        if not await document_repo.mark_available(s, ctx.document_id, ctx.attempt):
            raise Fenced
        await s.flush()
        await segment_service.refresh_search_flags(s, ctx.document_id)
        await stats_service.recalc_document(s, ctx.document_id)
        await stats_service.recalc_dataset(s, ctx.dataset_id)
        await s.commit()


async def _fail(ctx: DocCtx, failure: StageFailure) -> None:
    logger.warning(
        "文档处理失败",
        extra={"document_id": ctx.document_id, "stage": failure.stage, "code": failure.code, "msg_": failure.message},
    )
    async with get_session_factory()() as s:
        if not await document_repo.lock_dataset_row(s, ctx.dataset_id):
            return
        if await document_repo.mark_failed(
            s, ctx.document_id, ctx.attempt, stage=failure.stage, code=failure.code, message=failure.message
        ):
            await s.flush()
            await stats_service.recalc_dataset(s, ctx.dataset_id)
        await s.commit()
