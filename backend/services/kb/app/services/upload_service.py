"""文档上传、分段预览、提交处理（F-11，tech-design-m2 5.4）。

* 校验与解析在进程池执行（``PARSE_PROCESS_WORKERS`` 限制并发，``PARSE_TIMEOUT_SECONDS`` 限制等待时长）。
* 预览与正式处理共用 ``split_document``，保证 AC-37/AC-63 一致。
* 提交在 ``SELECT dataset FOR UPDATE`` 下单事务完成，提交后经 Redis Streams 投递 ``document.process`` 任务。
* 联网/长耗时操作前先 ``rollback`` 结束读事务，避免占用数据库连接；因此此类函数先把需要的字段取成局部变量。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
import uuid
from collections.abc import Callable
from concurrent.futures.process import BrokenProcessPool
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import Request
from fastapi import UploadFile as HttpUploadFile
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import TASK_STREAM, ChunkMode, DocStatus, ModelStatus
from app.models import AiModel, Dataset, Document, UploadFile
from app.parsers import ALLOWED_EXTS, ProcessError, parse, validate
from app.parsers.errors import FILE_EMPTY, FILE_TOO_LARGE, UNSUPPORTED_TYPE, broken
from app.parsers.registry import get_pool, normalize_ext, shutdown_pool
from app.repositories import document_repo, model_repo
from app.repositories.dataset_acl import require_dataset
from app.schemas.process_rule import ProcessRule, check_rule
from app.schemas.upload import (
    PreviewChildItem,
    PreviewResult,
    PreviewSegmentItem,
    SubmitRequest,
    SubmitResult,
    UploadFileResult,
)
from app.services import stats_service
from app.splitters import count_tokens, split_document
from app.storage.s3 import ObjectNotFound, get_storage
from platform_common.auth import runtime
from platform_common.auth.context import AuthContext
from platform_common.client_ip import get_client_ip
from platform_common.errors import BizError, CommonErrors
from platform_common.events.publisher import publish_after_commit
from platform_common.logging import get_request_id
from platform_common.oplog import OpLogEvent, emit_oplog, oplog_scope

logger = logging.getLogger(__name__)

ERR_MODEL_DISABLED = (409303, "向量模型已停用，请联系管理员")
ERR_UPLOAD_INVALID = (400508, "上传文件已失效，请重新上传")
ERR_LIMIT = (409502, "知识库文档数已达上限")
PREVIEW_SEGMENTS = 10
MAX_NAME_LENGTH = 200
READ_CHUNK = 1024 * 1024
FIRST_STAGE = "parse"
UQ_DOC_HASH = "uq_document_dataset_hash"

# 限制同一进程内并发分段（纯 Python CPU 密集，放线程里执行以免阻塞事件循环）
_split_gate = asyncio.Semaphore(2)

_MODE_LABEL = {ChunkMode.GENERAL.value: "通用分段", ChunkMode.PARENT_CHILD.value: "父子分段"}


# ---------------------------------------------------------------- 辅助


def _invalid_params(errors: list[tuple[str, str]]) -> BizError:
    code, message = CommonErrors.INVALID_PARAMS
    return BizError(code, message, {"errors": [{"field": f, "message": m} for f, m in errors]})


def split_filename(raw: str | None) -> tuple[str, str]:
    """返回 (展示名, 小写扩展名)：去掉路径与控制字符，超长截断且保留扩展名。"""
    base = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    ext = base.rsplit(".", 1)[1].strip().lower() if "." in base else ""
    if len(base) > MAX_NAME_LENGTH:
        suffix = f".{base.rsplit('.', 1)[1]}" if ext else ""
        base = base[: MAX_NAME_LENGTH - len(suffix)] + suffix
    return base, ext


async def _in_pool[T](fn: Callable[..., T], *args: object) -> T:
    """在解析进程池执行；超时/池崩溃/解析异常统一转为 BizError（400504 等）。"""
    settings = get_settings()
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(get_pool(settings.PARSE_PROCESS_WORKERS), fn, *args)
    try:
        return await asyncio.wait_for(fut, settings.PARSE_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise broken("文件解析超时", "TIMEOUT").to_biz_error() from exc
    except BrokenProcessPool as exc:
        shutdown_pool()  # 解析器崩溃（如损坏文件触发原生库异常）：重建池，文件按损坏处理
        logger.error("解析进程池异常，已重建", exc_info=True)
        raise broken().to_biz_error() from exc
    except ProcessError as exc:
        raise exc.to_biz_error() from exc


async def require_enabled_model(session: AsyncSession, dataset: Dataset) -> AiModel:
    model = await model_repo.get(session, dataset.embedding_model_id)
    if model is None or model.status != ModelStatus.ENABLED:
        raise BizError(*ERR_MODEL_DISABLED)
    return model


def check_mode(dataset: Dataset, rule: ProcessRule) -> None:
    if dataset.chunk_mode and dataset.chunk_mode != rule.mode:
        raise BizError(
            409503, f"该知识库的分段方式为{_MODE_LABEL.get(dataset.chunk_mode, dataset.chunk_mode)}，不能切换"
        )


def check_rule_for_model(rule: ProcessRule, model_max_tokens: int) -> None:
    errs = check_rule(rule, model_max_tokens)
    if errs:
        raise _invalid_params([(e.path, e.message) for e in errs])


async def _spool(file: HttpUploadFile, ext: str, max_bytes: int) -> tuple[Path, int, str]:
    """把上传内容流式写入临时文件并计算 SHA-256；超过上限立即 400502。调用方负责删除临时文件。"""
    fd, name = tempfile.mkstemp(prefix="kb-upload-", suffix=f".{ext}")
    path = Path(name)
    size = 0
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := await file.read(READ_CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise ProcessError(FILE_TOO_LARGE, "文件超过 15 MB", "TOO_LARGE").to_biz_error()
                digest.update(chunk)
                await asyncio.to_thread(out.write, chunk)
    except BaseException:
        _remove(path)
        raise
    return path, size, digest.hexdigest()


def _remove(path: Path) -> None:
    path.unlink(missing_ok=True)


def _storage_key(dataset_id: int, upload_file_id: int, file_hash: str, ext: str) -> str:
    return f"uploads/{dataset_id}/{upload_file_id}/{file_hash}.{ext}"


def _duplicate_error(items: list[tuple[int | None, str]], single_data: bool = False) -> BizError:
    first = items[0][1]
    if single_data:  # 上传：data={"existing_document_name": ...}
        return BizError(409501, f"与已有文档《{first}》内容重复", {"existing_document_name": first})
    message = (
        f"与已有文档《{first}》内容重复"
        if len(items) == 1
        else f"有 {len(items)} 个文件内容重复，例如与已有文档《{first}》重复"
    )
    return BizError(
        409501,
        message,
        {"duplicates": [{"upload_file_id": uid, "existing_document_name": name} for uid, name in items]},
    )


# ---------------------------------------------------------------- 上传


async def upload_file(
    session: AsyncSession, ctx: AuthContext, dataset_id: int, file: HttpUploadFile
) -> UploadFileResult:
    """5.4.1：校验顺序 409303 → 400501 → 400503/400502 → 400504 → 409501 → 409502。"""
    settings = get_settings()
    dataset = await require_dataset(session, ctx, dataset_id, "edit")
    await require_enabled_model(session, dataset)
    name, ext = split_filename(file.filename)
    if normalize_ext(ext) not in ALLOWED_EXTS:
        raise BizError(UNSUPPORTED_TYPE, "不支持的文件类型")
    ext = normalize_ext(ext)
    await session.rollback()  # 文件读取与解析期间不占用数据库连接

    tmp, size, file_hash = await _spool(file, ext, settings.UPLOAD_MAX_BYTES)
    try:
        if size == 0:
            raise BizError(FILE_EMPTY, "文件为空")
        await _in_pool(validate, str(tmp), ext)
        content = await asyncio.to_thread(tmp.read_bytes)
    finally:
        _remove(tmp)

    # 重新加锁前的最终校验（期间知识库可能被删除/回收权限/停用模型）
    dataset = await require_dataset(session, ctx, dataset_id, "edit")
    await require_enabled_model(session, dataset)
    dup = await document_repo.existing_names_by_hash(session, dataset.id, [file_hash])
    if file_hash in dup:
        raise _duplicate_error([(None, dup[file_hash])], single_data=True)
    if await document_repo.count_documents(session, dataset.id) >= settings.DATASET_MAX_DOCUMENTS:
        raise BizError(*ERR_LIMIT)

    record = UploadFile(
        dataset_id=dataset.id,
        name=name,
        file_ext=ext,
        file_size=size,
        file_hash=file_hash,
        storage_key="pending",
        expires_at=datetime.now(UTC) + timedelta(hours=settings.UPLOAD_FILE_TTL_HOURS),
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(record)
    await session.flush()
    record.storage_key = _storage_key(dataset.id, record.id, file_hash, ext)
    storage = get_storage()
    await storage.put_bytes(record.storage_key, content)
    try:
        await session.commit()
    except BaseException:
        await storage.delete(record.storage_key)
        raise
    return UploadFileResult(upload_file_id=record.id, name=name, file_ext=ext, file_size=size, file_hash=file_hash)


# ---------------------------------------------------------------- 预览


async def preview(
    session: AsyncSession, ctx: AuthContext, dataset_id: int, upload_file_id: int, rule: ProcessRule
) -> PreviewResult:
    """5.4.2：解析（缓存）→ 预处理 → 全量分段 → 返回前 10 个。"""
    dataset = await require_dataset(session, ctx, dataset_id, "edit")
    model = await require_enabled_model(session, dataset)
    record = await document_repo.get_valid_upload_file(session, dataset.id, upload_file_id, datetime.now(UTC))
    if record is None:
        raise BizError(*ERR_UPLOAD_INVALID)
    check_mode(dataset, rule)
    model_max = model.max_input_tokens
    check_rule_for_model(rule, model_max)
    uid, ext, storage_key, parsed_key, cached_tokens = (
        record.id,
        record.file_ext,
        record.storage_key,
        record.parsed_key,
        record.doc_token_count,
    )
    await session.rollback()  # 解析与分段期间不占用数据库连接

    text, cached = await _load_text(session, uid, ext, storage_key, parsed_key, cached_tokens)
    doc_tokens = cached if cached is not None else await asyncio.to_thread(count_tokens, text)
    async with _split_gate:
        try:
            drafts = await asyncio.to_thread(split_document, text, rule, model_max)
        except ProcessError as exc:
            raise exc.to_biz_error() from exc
    return PreviewResult(
        mode=rule.mode,
        total_segments=len(drafts),
        total_child_chunks=sum(len(d.children) for d in drafts),
        doc_token_count=doc_tokens,
        segments=[
            PreviewSegmentItem(
                position=d.position,
                content=d.content,
                char_count=d.char_count,
                token_count=d.token_count,
                children=[
                    PreviewChildItem(
                        position=c.position, content=c.content, char_count=c.char_count, token_count=c.token_count
                    )
                    for c in d.children
                ],
            )
            for d in drafts[:PREVIEW_SEGMENTS]
        ],
    )


async def _load_text(
    session: AsyncSession, uid: int, ext: str, storage_key: str, parsed_key: str | None, cached_tokens: int | None
) -> tuple[str, int | None]:
    """返回 (解析文本, 已缓存的全文 token 数或 None)。无缓存时解析并把文本写入对象存储。"""
    storage = get_storage()
    if parsed_key:
        try:
            return (await storage.get_bytes(parsed_key)).decode("utf-8"), cached_tokens
        except ObjectNotFound:
            pass  # 缓存丢失：重新解析
    try:
        raw = await storage.get_bytes(storage_key)
    except ObjectNotFound as exc:
        raise BizError(*ERR_UPLOAD_INVALID) from exc
    fd, name = tempfile.mkstemp(prefix="kb-parse-", suffix=f".{ext}")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            await asyncio.to_thread(out.write, raw)
        text = await _in_pool(parse, str(tmp), ext)
    finally:
        _remove(tmp)
    key = f"parsed/{uid}.txt"
    await storage.put_bytes(key, text.encode("utf-8"), "text/plain; charset=utf-8")
    tokens = await asyncio.to_thread(count_tokens, text)
    await session.execute(update(UploadFile).where(UploadFile.id == uid).values(parsed_key=key, doc_token_count=tokens))
    await session.commit()
    return text, tokens


# ---------------------------------------------------------------- 提交


async def submit(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, body: SubmitRequest
) -> SubmitResult:
    """5.4.3：单事务（锁知识库行）创建文档并标记上传文件已消费，提交后投递处理任务。"""
    settings = get_settings()
    rule = body.process_rule
    async with oplog_scope(
        request, ctx, module="document", action="upload", target_type="dataset", target_id=dataset_id
    ) as h:
        dataset = await require_dataset(session, ctx, dataset_id, "edit", for_update=True)
        h.set_target(dataset.id, dataset.name)
        model = await require_enabled_model(session, dataset)
        check_mode(dataset, rule)
        check_rule_for_model(rule, model.max_input_tokens)
        if await document_repo.count_documents(session, dataset.id) + len(body.upload_file_ids) > (
            settings.DATASET_MAX_DOCUMENTS
        ):
            raise BizError(*ERR_LIMIT)
        files = await document_repo.lock_valid_upload_files(
            session, dataset.id, body.upload_file_ids, datetime.now(UTC)
        )
        if len(files) != len(body.upload_file_ids):
            raise BizError(*ERR_UPLOAD_INVALID)
        ordered = [files[i] for i in body.upload_file_ids]

        existing = await document_repo.existing_names_by_hash(session, dataset.id, {f.file_hash for f in ordered})
        dups: list[tuple[int | None, str]] = []
        first_in_batch: dict[str, str] = {}
        for f in ordered:
            if f.file_hash in existing:
                dups.append((f.id, existing[f.file_hash]))
            elif f.file_hash in first_in_batch:
                dups.append((f.id, first_in_batch[f.file_hash]))
            else:
                first_in_batch[f.file_hash] = f.name
        if dups:
            raise _duplicate_error(dups)

        rule_dump = rule.model_dump(exclude_none=True)
        docs: list[Document] = []
        for f in ordered:
            doc = Document(
                dataset_id=dataset.id,
                upload_file_id=f.id,
                name=f.name,
                file_ext=f.file_ext,
                file_size=f.file_size,
                file_hash=f.file_hash,
                storage_key=f.storage_key,
                parsed_key=f.parsed_key,
                chunk_mode=rule.mode,
                process_rule=rule_dump,
                status=DocStatus.QUEUED.value,
                process_attempt=1,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
            )
            session.add(doc)
            docs.append(doc)
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            if UQ_DOC_HASH in str(getattr(exc.orig, "constraint_name", "") or exc.orig):
                raise BizError(409501, "与已有文档内容重复") from exc
            raise BizError(*ERR_UPLOAD_INVALID) from exc
        for f, doc in zip(ordered, docs, strict=True):
            f.consumed_document_id = doc.id
            f.updated_by = ctx.user_id
        dataset.chunk_mode = rule.mode
        dataset.last_process_rule = rule_dump
        dataset.updated_by = ctx.user_id
        await session.flush()
        await stats_service.recalc_dataset(session, dataset.id)
        for doc in docs:
            publish_after_commit(
                session,
                TASK_STREAM,
                "document.process",
                {"document_id": doc.id, "attempt": doc.process_attempt, "from_stage": FIRST_STAGE},
            )
        result = SubmitResult.model_validate(
            {"documents": [{"id": d.id, "name": d.name, "status": d.status} for d in docs]}
        )
        dataset_name = dataset.name
        await session.commit()
        h.suppress = True  # 成功时按文档逐条记录（契约：每个文档一条 document/upload）
    await _log_documents(request, ctx, dataset_id, dataset_name, docs)
    return result


async def _log_documents(
    request: Request, ctx: AuthContext, dataset_id: int, dataset_name: str, docs: list[Document]
) -> None:
    settings = runtime.get_settings()
    for d in docs:
        await emit_oplog(
            OpLogEvent(
                event_id=str(uuid.uuid4()),
                service=settings.SERVICE_NAME,
                occurred_at=datetime.now(UTC),
                operator_id=ctx.user_id,
                operator_username=ctx.username,
                operator_name=ctx.name,
                company_id=ctx.company_id,
                dept_id=ctx.org_id,
                module="document",
                action="upload",
                target_type="document",
                target_id=str(d.id),
                target_name=d.name,
                summary={
                    "dataset_id": dataset_id,
                    "dataset_name": dataset_name,
                    "file_ext": d.file_ext,
                    "file_size": d.file_size,
                    "chunk_mode": d.chunk_mode,
                },
                result="success",
                ip=get_client_ip(request, settings.TRUSTED_PROXIES),
                user_agent=request.headers.get("user-agent"),
                request_id=get_request_id(),
            )
        )
