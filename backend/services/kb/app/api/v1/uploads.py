"""上传、预览、提交接口（tech-design-m2 5.4）。路径挂在 ``/kb/datasets/{id}`` 下。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.upload import PreviewRequest, PreviewResult, SubmitRequest, SubmitResult, UploadFileResult
from app.services import upload_service
from platform_common.auth.context import AuthContext
from platform_common.auth.deps import require_perm
from platform_common.db import get_db
from platform_common.response import ApiResponse, ok

router = APIRouter(prefix="/kb/datasets/{dataset_id}", tags=["uploads"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
UploadCtx = Annotated[AuthContext, Depends(require_perm("kb:document:upload"))]


@router.post(
    "/upload-files",
    summary="上传单个文件（kb:document:upload；ACL 可编辑；multipart 字段 file）",
    response_model=ApiResponse[UploadFileResult],
)
async def upload_file(
    dataset_id: int, ctx: UploadCtx, session: DbDep, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    return ok(await upload_service.upload_file(session, ctx, dataset_id, file))


@router.post(
    "/documents/preview",
    summary="分段预览（kb:document:upload；ACL 可编辑；返回前 10 个分段）",
    response_model=ApiResponse[PreviewResult],
)
async def preview(dataset_id: int, body: PreviewRequest, ctx: UploadCtx, session: DbDep) -> dict[str, Any]:
    return ok(await upload_service.preview(session, ctx, dataset_id, body.upload_file_id, body.process_rule))


@router.post(
    "/documents",
    summary="提交处理（kb:document:upload；ACL 可编辑；文档进入排队中并投递任务）",
    response_model=ApiResponse[SubmitResult],
)
async def submit_documents(
    dataset_id: int, body: SubmitRequest, request: Request, ctx: UploadCtx, session: DbDep
) -> dict[str, Any]:
    return ok(await upload_service.submit(session, ctx, request, dataset_id, body))
