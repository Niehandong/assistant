"""知识库管理视图接口（tech-design-m2 5.8，F-20）。

只读审计 + 所有权转移；**没有**任何编辑、上传、下载、删除、召回测试路由（AC-67）。
固定路径 ``/datasets/batch-transfer`` 与 ``/datasets/{id}`` 方法不同，互不冲突。
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.admin_repo import AdminFilter
from app.repositories.document_repo import DocumentFilter
from app.schemas.admin import (
    AdminDatasetDetail,
    AdminDatasetItem,
    AdminOwnerOption,
    BatchTransferBody,
    BatchTransferResult,
    OwnerStatus,
    TransferBody,
)
from app.schemas.assignment import AssignableUser
from app.schemas.document import DocumentDetail, DocumentItem
from app.schemas.segment import SegmentItem
from app.services import admin_service, transfer_service
from platform_common.auth.context import AuthContext
from platform_common.auth.deps import require_perm
from platform_common.db import get_db
from platform_common.pagination import PageParamsDep
from platform_common.response import ApiResponse, Page, ok, page

router = APIRouter(prefix="/kb/admin", tags=["admin"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
ListCtx = Annotated[AuthContext, Depends(require_perm("kb:admin:list"))]
ViewCtx = Annotated[AuthContext, Depends(require_perm("kb:admin:view"))]
TransferCtx = Annotated[AuthContext, Depends(require_perm("kb:admin:transfer"))]


@router.get("/datasets", summary="管理视图知识库列表（kb:admin:list；按数据范围）")
async def list_datasets(
    ctx: ListCtx,
    session: DbDep,
    pp: PageParamsDep,
    keyword: Annotated[str | None, Query(max_length=50)] = None,
    owner_keyword: Annotated[str | None, Query(max_length=50)] = None,
    owner_id: Annotated[int | None, Query(ge=1)] = None,
    org_id: Annotated[int | None, Query(ge=1)] = None,
    owner_status: Annotated[OwnerStatus | None, Query()] = None,
    pending_handover: Annotated[bool, Query()] = False,
) -> ApiResponse[Page[AdminDatasetItem]]:
    f = AdminFilter(
        keyword=keyword.strip() if keyword else None,
        owner_keyword=owner_keyword.strip() if owner_keyword else None,
        owner_id=owner_id,
        org_id=org_id,
        owner_status=owner_status,
        pending_handover=pending_handover,
    )
    items, total = await admin_service.list_datasets(session, ctx, f, pp)
    return page(items, total, pp.page, pp.page_size)  # type: ignore[return-value]


@router.get("/datasets/{dataset_id}", summary="管理视图详情（kb:admin:view；按规则记审计日志）")
async def get_dataset(
    dataset_id: int,
    request: Request,
    ctx: ViewCtx,
    session: DbDep,
    audit_entry: Annotated[bool, Query()] = False,
) -> ApiResponse[AdminDatasetDetail]:
    return ok(await admin_service.get_dataset(session, ctx, request, dataset_id, audit_entry))  # type: ignore[return-value]


@router.get("/datasets/{dataset_id}/documents", summary="管理视图文档列表（kb:admin:view；只读，不记日志）")
async def list_documents(
    dataset_id: int,
    ctx: ViewCtx,
    session: DbDep,
    pp: PageParamsDep,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    status: Annotated[
        Literal["queued", "parsing", "splitting", "indexing", "available", "failed", "processing"] | None, Query()
    ] = None,
    enabled: Annotated[bool | None, Query()] = None,
    sort_by: Annotated[Literal["created_at", "char_count", "hit_count"], Query()] = "created_at",
    sort_order: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> ApiResponse[Page[DocumentItem]]:
    f = DocumentFilter(
        keyword=keyword.strip() if keyword else None,
        status=status,
        enabled=enabled,
        sort_by=sort_by,
        sort_desc=sort_order == "desc",
    )
    items, total = await admin_service.list_documents(session, ctx, dataset_id, f, pp)
    return page(items, total, pp.page, pp.page_size)  # type: ignore[return-value]


@router.get(
    "/datasets/{dataset_id}/documents/{document_id}", summary="管理视图文档详情（kb:admin:view；只读，不记日志）"
)
async def get_document(dataset_id: int, document_id: int, ctx: ViewCtx, session: DbDep) -> ApiResponse[DocumentDetail]:
    return ok(await admin_service.get_document(session, ctx, dataset_id, document_id))  # type: ignore[return-value]


@router.get(
    "/datasets/{dataset_id}/documents/{document_id}/segments",
    summary="管理视图分段列表（kb:admin:view；只读，按规则记审计日志）",
)
async def list_segments(
    dataset_id: int,
    document_id: int,
    request: Request,
    ctx: ViewCtx,
    session: DbDep,
    pp: PageParamsDep,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    enabled: Annotated[bool | None, Query()] = None,
    audit_entry: Annotated[bool, Query()] = False,
) -> ApiResponse[Page[SegmentItem]]:
    items, total = await admin_service.list_segments(
        session,
        ctx,
        request,
        dataset_id,
        document_id,
        keyword=keyword.strip() if keyword else None,
        enabled=enabled,
        audit_entry=audit_entry,
        pp=pp,
    )
    return page(items, total, pp.page, pp.page_size)  # type: ignore[return-value]


@router.post("/datasets/batch-transfer", summary="批量转移所有权（kb:admin:transfer；事务内行锁，冲突整体回滚）")
async def batch_transfer(
    body: BatchTransferBody, request: Request, ctx: TransferCtx, session: DbDep
) -> ApiResponse[BatchTransferResult]:
    return ok(await transfer_service.admin_batch_transfer(session, ctx, request, body))  # type: ignore[return-value]


@router.post("/datasets/{dataset_id}/transfer", summary="转移所有权（kb:admin:transfer；携带 version）")
async def transfer(
    dataset_id: int, body: TransferBody, request: Request, ctx: TransferCtx, session: DbDep
) -> ApiResponse[AdminDatasetItem]:
    return ok(await transfer_service.admin_transfer(session, ctx, request, dataset_id, body))  # type: ignore[return-value]


@router.get("/receivers", summary="转移接收人候选（kb:admin:transfer；数据范围内、启用、未删除）")
async def receivers(
    ctx: TransferCtx,
    session: DbDep,
    pp: PageParamsDep,
    keyword: Annotated[str | None, Query(max_length=50)] = None,
) -> ApiResponse[Page[AssignableUser]]:
    items, total = await admin_service.list_receivers(session, ctx, keyword.strip() if keyword else None, pp)
    return page(items, total, pp.page, pp.page_size)  # type: ignore[return-value]


@router.get("/owners", summary="范围内知识库的所有者（kb:admin:transfer；含停用/删除，最多 50 条）")
async def owners(
    ctx: TransferCtx, session: DbDep, keyword: Annotated[str | None, Query(max_length=50)] = None
) -> ApiResponse[list[AdminOwnerOption]]:
    return ok(await admin_service.list_owners(session, ctx, keyword.strip() if keyword else None))  # type: ignore[return-value]
