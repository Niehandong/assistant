"""文档管理接口（tech-design-m2 5.5）。固定路径（progress/enabled/batch-delete）声明在 ``/{document_id}`` 之前。"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.document_repo import DocumentFilter
from app.schemas.document import (
    BatchDeleteRequest,
    DeleteResult,
    DocumentDetail,
    DocumentItem,
    DocumentProgressItem,
    EnabledRequest,
    EnabledResult,
    ReprocessRequest,
)
from app.services import document_service
from platform_common.auth.context import AuthContext
from platform_common.auth.deps import require_perm
from platform_common.db import get_db
from platform_common.errors import BizError, CommonErrors
from platform_common.pagination import PageParamsDep
from platform_common.response import ApiResponse, Page, ok, page

router = APIRouter(prefix="/kb/datasets/{dataset_id}/documents", tags=["documents"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
ListCtx = Annotated[AuthContext, Depends(require_perm("kb:dataset:list"))]
UpdateCtx = Annotated[AuthContext, Depends(require_perm("kb:document:update"))]
DeleteCtx = Annotated[AuthContext, Depends(require_perm("kb:document:delete"))]
DownloadCtx = Annotated[AuthContext, Depends(require_perm("kb:document:download"))]


@router.get("", summary="文档列表（kb:dataset:list；ACL 只读）", response_model=ApiResponse[Page[DocumentItem]])
async def list_documents(
    dataset_id: int,
    ctx: ListCtx,
    session: DbDep,
    pp: PageParamsDep,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    status: Annotated[
        Literal["queued", "parsing", "splitting", "indexing", "available", "failed", "processing"] | None, Query()
    ] = None,
    enabled: Annotated[bool | None, Query()] = None,
    sort_by: Annotated[Literal["created_at", "char_count", "hit_count"], Query()] = "created_at",
    sort_order: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> dict[str, Any]:
    f = DocumentFilter(
        keyword=keyword.strip() if keyword else None,
        status=status,
        enabled=enabled,
        sort_by=sort_by,
        sort_desc=sort_order == "desc",
    )
    items, total = await document_service.list_documents(session, ctx, dataset_id, f, pp.offset, pp.limit)
    return page(items, total, pp.page, pp.page_size)


@router.get(
    "/progress",
    summary="文档处理进度（kb:dataset:list；ACL 只读；ids 逗号分隔，最多 50 个）",
    response_model=ApiResponse[list[DocumentProgressItem]],
)
async def document_progress(
    dataset_id: int, ctx: ListCtx, session: DbDep, ids: Annotated[str, Query(description="逗号分隔，≤50")]
) -> dict[str, Any]:
    parsed: list[int] = []
    for part in ids.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdecimal() or int(part) < 1 or len(part) > 18:
            raise BizError(*CommonErrors.INVALID_PARAMS)
        parsed.append(int(part))
    parsed = list(dict.fromkeys(parsed))
    if len(parsed) > document_service.MAX_PROGRESS_IDS:
        raise BizError(*CommonErrors.INVALID_PARAMS)
    return ok(await document_service.progress(session, ctx, dataset_id, parsed))


@router.put(
    "/enabled",
    summary="批量启用/禁用（kb:document:update；ACL 可编辑）",
    response_model=ApiResponse[EnabledResult],
)
async def set_enabled(
    dataset_id: int, body: EnabledRequest, request: Request, ctx: UpdateCtx, session: DbDep
) -> dict[str, Any]:
    return ok(await document_service.set_enabled(session, ctx, request, dataset_id, body.document_ids, body.enabled))


@router.post(
    "/batch-delete",
    summary="批量删除（kb:document:delete；ACL 可编辑；处理中也可删除）",
    response_model=ApiResponse[DeleteResult],
)
async def batch_delete(
    dataset_id: int, body: BatchDeleteRequest, request: Request, ctx: DeleteCtx, session: DbDep
) -> dict[str, Any]:
    return ok(await document_service.batch_delete(session, ctx, request, dataset_id, body.document_ids))


@router.get(
    "/{document_id}", summary="文档详情（kb:dataset:list；ACL 只读）", response_model=ApiResponse[DocumentDetail]
)
async def get_document(dataset_id: int, document_id: int, ctx: ListCtx, session: DbDep) -> dict[str, Any]:
    return ok(await document_service.get_detail(session, ctx, dataset_id, document_id))


@router.post(
    "/{document_id}/reprocess",
    summary="重新分段（kb:document:update；ACL 可编辑；仅可用/失败文档）",
    response_model=ApiResponse[None],
)
async def reprocess(
    dataset_id: int, document_id: int, body: ReprocessRequest, request: Request, ctx: UpdateCtx, session: DbDep
) -> dict[str, Any]:
    await document_service.reprocess(session, ctx, request, dataset_id, document_id, body)
    return ok()


@router.post(
    "/{document_id}/retry",
    summary="重试失败文档（kb:document:update；ACL 可编辑；从失败阶段继续）",
    response_model=ApiResponse[None],
)
async def retry(dataset_id: int, document_id: int, request: Request, ctx: UpdateCtx, session: DbDep) -> dict[str, Any]:
    await document_service.retry(session, ctx, request, dataset_id, document_id)
    return ok()


@router.get(
    "/{document_id}/download",
    summary="下载原文件（kb:document:download；ACL 只读；成功为文件流，失败为统一 JSON 且 HTTP 状态码非 2xx）",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "原文件流"}},
)
async def download(dataset_id: int, document_id: int, ctx: DownloadCtx, session: DbDep) -> StreamingResponse:
    doc, stream = await document_service.open_download(session, ctx, dataset_id, document_id)
    return StreamingResponse(
        stream,
        media_type=document_service.guess_content_type(doc.file_ext),
        headers={
            "Content-Disposition": document_service.content_disposition(doc.name),
            "Content-Length": str(doc.file_size),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
