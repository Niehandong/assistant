"""文档管理（F-13，tech-design-m2 5.5）：列表/进度/详情、启停、删除、重试、重新分段、下载。

写操作统一：``require_dataset(..., "edit", for_update=True)`` 锁知识库行（锁序：知识库 → 文档，与 worker 一致），
再锁目标文档行并校验其属于本库（防止通过 ID 越权）。
"""

from __future__ import annotations

import mimetypes
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from fastapi import Request
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import TASK_STREAM, DocStatus
from app.models import Document
from app.repositories import document_repo
from app.repositories.dataset_acl import require_dataset
from app.repositories.document_repo import DocumentFilter
from app.schemas.document import (
    DeleteResult,
    DocumentDetail,
    DocumentItem,
    DocumentProgressItem,
    EnabledResult,
    ProgressInfo,
    ReprocessRequest,
    UploaderBrief,
)
from app.services import stats_service, upload_service
from app.services.segment_service import refresh_search_flags
from app.storage.s3 import ObjectNotFound, get_storage
from platform_common.auth import runtime
from platform_common.auth.context import AuthContext
from platform_common.client_ip import get_client_ip
from platform_common.errors import BizError, CommonErrors
from platform_common.events.publisher import publish_after_commit
from platform_common.logging import get_request_id
from platform_common.oplog import OpLogEvent, emit_oplog, oplog_scope

ERR_PROCESSING = (409504, "文档处理中，暂不能执行该操作")
ERR_NOT_FAILED = (409505, "只有处理失败的文档可以重试")
ERR_FILE_GONE = (404000, "原文件不存在或已被清理")
MAX_PROGRESS_IDS = 50

_PROCESSING = {s.value for s in (DocStatus.QUEUED, DocStatus.PARSING, DocStatus.SPLITTING, DocStatus.INDEXING)}


# ---------------------------------------------------------------- 展示转换


def _progress(d: Document) -> ProgressInfo | None:
    """处理中返回 ``{done,total}``；终态为 None。"""
    if d.status in _PROCESSING:
        return ProgressInfo(done=d.progress_done, total=d.progress_total)
    return None


def _item_fields(d: Document, uploader: str | None) -> dict[str, Any]:
    return {
        "id": d.id,
        "name": d.name,
        "file_ext": d.file_ext,
        "file_size": d.file_size,
        "chunk_mode": d.chunk_mode,
        "char_count": d.char_count,
        "segment_count": d.segment_count,
        "child_count": d.child_count,
        "hit_count": d.hit_count,
        "uploaded_by": UploaderBrief(id=d.created_by or 0, name=uploader or "未知用户"),
        "created_at": d.created_at,
        "status": d.status,
        "progress": _progress(d),
        "error_code": d.error_code if d.status == DocStatus.FAILED else None,
        "error_message": d.error_message if d.status == DocStatus.FAILED else None,
        "enabled": d.enabled,
        "version": d.version,
    }


# ---------------------------------------------------------------- 查询


async def list_documents(
    session: AsyncSession, ctx: AuthContext, dataset_id: int, f: DocumentFilter, offset: int, limit: int
) -> tuple[list[DocumentItem], int]:
    await require_dataset(session, ctx, dataset_id, "read")
    return await list_documents_unchecked(session, dataset_id, f, offset, limit)


async def list_documents_unchecked(
    session: AsyncSession, dataset_id: int, f: DocumentFilter, offset: int, limit: int
) -> tuple[list[DocumentItem], int]:
    """不校验 ACL：调用方（管理视图）已按其自身规则确认可见性。"""
    rows, total = await document_repo.list_documents(session, dataset_id, f, offset, limit)
    return [DocumentItem(**_item_fields(d, name)) for d, name in rows], total


async def progress(
    session: AsyncSession, ctx: AuthContext, dataset_id: int, ids: list[int]
) -> list[DocumentProgressItem]:
    await require_dataset(session, ctx, dataset_id, "read")
    docs = await document_repo.list_by_ids(session, dataset_id, ids)
    return [
        DocumentProgressItem(
            id=d.id,
            status=d.status,  # type: ignore[arg-type]
            progress=_progress(d),
            error_code=d.error_code if d.status == DocStatus.FAILED else None,
            error_message=d.error_message if d.status == DocStatus.FAILED else None,
            segment_count=d.segment_count,
            child_count=d.child_count,
            char_count=d.char_count,
        )
        for d in docs
    ]


async def get_detail(session: AsyncSession, ctx: AuthContext, dataset_id: int, document_id: int) -> DocumentDetail:
    await require_dataset(session, ctx, dataset_id, "read")
    return await get_detail_unchecked(session, dataset_id, document_id)


async def get_detail_unchecked(session: AsyncSession, dataset_id: int, document_id: int) -> DocumentDetail:
    """不校验 ACL：调用方（管理视图）已按其自身规则确认可见性。"""
    d = await document_repo.get_in_dataset(session, dataset_id, document_id)
    if d is None:
        raise BizError(*CommonErrors.NOT_FOUND)
    name = await document_repo.uploader_name(session, d.created_by)
    return DocumentDetail(**_item_fields(d, name), process_rule=d.process_rule)


# ---------------------------------------------------------------- 启停


async def set_enabled(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, ids: list[int], enabled: bool
) -> EnabledResult:
    async with oplog_scope(
        request,
        ctx,
        module="document",
        action="enable" if enabled else "disable",
        target_type="dataset",
        target_id=dataset_id,
    ) as h:
        dataset = await require_dataset(session, ctx, dataset_id, "edit", for_update=True)
        h.set_target(dataset.id, dataset.name)
        docs = await document_repo.list_by_ids(session, dataset.id, ids, for_update=True)
        if len(docs) != len(ids):
            raise BizError(*CommonErrors.NOT_FOUND)  # 整体拒绝，不泄露哪些 ID 存在
        for d in docs:
            if d.enabled != enabled:
                d.enabled = enabled
                d.version += 1
                d.updated_by = ctx.user_id
        await session.flush()
        for d in docs:
            await refresh_search_flags(session, d.id)
        await stats_service.recalc_dataset(session, dataset.id)
        await session.commit()
        h.summary = {"document_ids": ids, "enabled": enabled}
        return EnabledResult(updated=len(docs))


# ---------------------------------------------------------------- 删除


async def batch_delete(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, ids: list[int]
) -> DeleteResult:
    """处理中也可删除：``is_deleted`` + ``process_attempt+1`` 使在途任务被栅栏拦截。"""
    async with oplog_scope(
        request, ctx, module="document", action="delete", target_type="dataset", target_id=dataset_id
    ) as h:
        dataset = await require_dataset(session, ctx, dataset_id, "edit", for_update=True)
        h.set_target(dataset.id, dataset.name)
        docs = await document_repo.list_by_ids(session, dataset.id, ids, for_update=True)
        if len(docs) != len(ids):
            raise BizError(*CommonErrors.NOT_FOUND)
        await document_repo.soft_delete_content(session, [d.id for d in docs], ctx.user_id)
        for d in docs:
            d.is_deleted = True
            d.process_attempt += 1
            d.updated_by = ctx.user_id
        await session.flush()
        await stats_service.recalc_dataset(session, dataset.id)
        if not await document_repo.has_alive_documents(session, dataset.id):
            dataset.chunk_mode = None  # 文档全部删除后可重新选择分段方式
            dataset.updated_by = ctx.user_id
        dataset_name = dataset.name
        deleted = [(d.id, d.name, d.file_ext, d.file_size, d.status) for d in docs]
        await session.commit()
        h.suppress = True  # 成功时每文档一条 document/delete
    for doc_id, name, ext, size, status in deleted:
        await _log_document(
            request,
            ctx,
            "delete",
            doc_id,
            name,
            {
                "dataset_id": dataset_id,
                "dataset_name": dataset_name,
                "file_ext": ext,
                "file_size": size,
                "status": status,
            },
        )
    return DeleteResult(deleted=len(deleted))


# ---------------------------------------------------------------- 重试 / 重新分段


def _enqueue(session: AsyncSession, d: Document, from_stage: str, operator_id: int) -> None:
    """同一事务内：attempt+1、queued、刷新排队计时、清空错误；提交后投递任务。"""
    d.process_attempt += 1
    d.status = DocStatus.QUEUED.value
    d.progress_updated_at = func.now()
    d.failed_stage = None
    d.error_code = None
    d.error_message = None
    d.version += 1
    d.updated_by = operator_id
    publish_after_commit(
        session,
        TASK_STREAM,
        "document.process",
        {"document_id": d.id, "attempt": d.process_attempt, "from_stage": from_stage},
    )


async def retry(session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, document_id: int) -> None:
    async with oplog_scope(
        request, ctx, module="document", action="retry", target_type="document", target_id=document_id
    ) as h:
        dataset = await require_dataset(session, ctx, dataset_id, "edit", for_update=True)
        d = await document_repo.get_in_dataset(session, dataset.id, document_id, for_update=True)
        if d is None:
            raise BizError(*CommonErrors.NOT_FOUND)
        h.set_target(d.id, d.name)
        if d.status != DocStatus.FAILED:
            raise BizError(*ERR_NOT_FAILED)
        await upload_service.require_enabled_model(session, dataset)
        h.summary = {"dataset_id": dataset.id, "failed_stage": d.failed_stage, "error_code": d.error_code}
        _enqueue(session, d, d.failed_stage or "split", ctx.user_id)
        await session.flush()
        await refresh_search_flags(session, d.id)
        await stats_service.recalc_dataset(session, dataset.id)
        await session.commit()


async def reprocess(
    session: AsyncSession,
    ctx: AuthContext,
    request: Request,
    dataset_id: int,
    document_id: int,
    body: ReprocessRequest,
) -> None:
    """重新分段：丢弃全部现有分段（含人工修改），立即 queued 且不参与检索，从 split 阶段重新处理。"""
    async with oplog_scope(
        request, ctx, module="document", action="reprocess", target_type="document", target_id=document_id
    ) as h:
        dataset = await require_dataset(session, ctx, dataset_id, "edit", for_update=True)
        d = await document_repo.get_in_dataset(session, dataset.id, document_id, for_update=True)
        if d is None:
            raise BizError(*CommonErrors.NOT_FOUND)
        h.set_target(d.id, d.name)
        if d.status not in (DocStatus.AVAILABLE, DocStatus.FAILED):
            raise BizError(*ERR_PROCESSING)
        if d.version != body.version:
            raise BizError(*CommonErrors.VERSION_CONFLICT)
        model = await upload_service.require_enabled_model(session, dataset)
        upload_service.check_mode(dataset, body.process_rule)
        upload_service.check_rule_for_model(body.process_rule, model.max_input_tokens)
        before_rule = d.process_rule
        await document_repo.soft_delete_content(session, [d.id], ctx.user_id)
        d.process_rule = body.process_rule.model_dump(exclude_none=True)
        d.chunk_mode = body.process_rule.mode
        d.progress_done = 0
        d.progress_total = 0
        _enqueue(session, d, "split", ctx.user_id)
        await session.flush()
        await refresh_search_flags(session, d.id)
        await stats_service.recalc_document(session, d.id)
        await stats_service.recalc_dataset(session, dataset.id)
        h.summary = {
            "dataset_id": dataset.id,
            "dataset_name": dataset.name,
            "before": {"process_rule": before_rule},
            "after": {"process_rule": d.process_rule},
        }
        await session.commit()


# ---------------------------------------------------------------- 下载


_ASCII_SAFE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- ")


def content_disposition(filename: str) -> str:
    """RFC 6266：ASCII 回退名 + ``filename*=UTF-8''`` 百分号编码。"""
    fallback = "".join(c if c in _ASCII_SAFE else "_" for c in filename) or "download"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


@dataclass(frozen=True)
class DownloadInfo:
    name: str
    file_ext: str
    file_size: int


async def open_download(
    session: AsyncSession, ctx: AuthContext, dataset_id: int, document_id: int
) -> tuple[DownloadInfo, AsyncIterator[bytes]]:
    """校验 ACL（只读）、文档归属与对象存在后返回流；所有错误都在开始流式输出之前抛出（非 2xx 状态码）。"""
    await require_dataset(session, ctx, dataset_id, "read")
    d = await document_repo.get_in_dataset(session, dataset_id, document_id)
    if d is None:
        raise BizError(*CommonErrors.NOT_FOUND)
    info, key = DownloadInfo(d.name, d.file_ext, d.file_size), d.storage_key
    # 读事务到此结束，不在对象存储访问与流式传输期间占用数据库连接
    await session.rollback()
    if not await get_storage().exists(key):
        raise BizError(*ERR_FILE_GONE)
    return info, _stream(key)


async def _stream(key: str) -> AsyncIterator[bytes]:
    try:
        async for chunk in get_storage().iter_bytes(key):
            yield chunk
    except ObjectNotFound:  # 校验后被清理的极端竞态：连接已开始输出，只能终止
        return


def guess_content_type(file_ext: str) -> str:
    return mimetypes.types_map.get(f".{file_ext.lower()}") or "application/octet-stream"


# ---------------------------------------------------------------- 操作日志


async def _log_document(
    request: Request, ctx: AuthContext, action: str, doc_id: int, name: str, summary: dict[str, Any]
) -> None:
    settings = runtime.get_settings()
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
            action=action,
            target_type="document",
            target_id=str(doc_id),
            target_name=name,
            summary=summary,
            result="success",
            ip=get_client_ip(request, settings.TRUSTED_PROXIES),
            user_agent=request.headers.get("user-agent"),
            request_id=get_request_id(),
        )
    )
