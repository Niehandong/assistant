"""分段管理接口（tech-design-m2 5.6）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.segment import (
    ChildChunkItem,
    ChildCreate,
    ChildUpdate,
    SegmentCreate,
    SegmentEnabledBody,
    SegmentItem,
    SegmentUpdate,
)
from app.services import segment_service
from platform_common.auth.context import AuthContext
from platform_common.auth.deps import require_perm
from platform_common.db import get_db
from platform_common.pagination import PageParamsDep
from platform_common.response import ApiResponse, Page, ok, page

router = APIRouter(prefix="/kb/datasets/{dataset_id}", tags=["segments"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
ListCtx = Annotated[AuthContext, Depends(require_perm("kb:dataset:list"))]
EditCtx = Annotated[AuthContext, Depends(require_perm("kb:segment:update"))]


@router.get(
    "/documents/{document_id}/segments",
    summary="分段列表（kb:dataset:list；ACL 只读；父子分段带当前代子块）",
    response_model=ApiResponse[Page[SegmentItem]],
)
async def list_segments(
    dataset_id: int,
    document_id: int,
    ctx: ListCtx,
    session: DbDep,
    pp: PageParamsDep,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    enabled: Annotated[bool | None, Query()] = None,
) -> dict[str, Any]:
    items, total = await segment_service.list_segments(
        session,
        ctx,
        dataset_id,
        document_id,
        keyword=keyword.strip() if keyword else None,
        enabled=enabled,
        offset=pp.offset,
        limit=pp.limit,
    )
    return page(items, total, pp.page, pp.page_size)


@router.post(
    "/documents/{document_id}/segments",
    summary="新增通用分段（kb:segment:update；ACL 可编辑；追加到文档末尾）",
    response_model=ApiResponse[SegmentItem],
)
async def create_segment(
    dataset_id: int, document_id: int, body: SegmentCreate, request: Request, ctx: EditCtx, session: DbDep
) -> dict[str, Any]:
    return ok(await segment_service.create_segment(session, ctx, request, dataset_id, document_id, body))


@router.put(
    "/segments/{segment_id}",
    summary="编辑分段内容/关键词（kb:segment:update；ACL 可编辑；异步重建索引）",
    response_model=ApiResponse[SegmentItem],
)
async def update_segment(
    dataset_id: int, segment_id: int, body: SegmentUpdate, request: Request, ctx: EditCtx, session: DbDep
) -> dict[str, Any]:
    return ok(await segment_service.update_segment(session, ctx, request, dataset_id, segment_id, body))


@router.put(
    "/segments/{segment_id}/enabled",
    summary="启用/禁用分段（kb:segment:update；ACL 可编辑；父块整体生效）",
    response_model=ApiResponse[SegmentItem],
)
async def set_segment_enabled(
    dataset_id: int, segment_id: int, body: SegmentEnabledBody, request: Request, ctx: EditCtx, session: DbDep
) -> dict[str, Any]:
    return ok(await segment_service.set_segment_enabled(session, ctx, request, dataset_id, segment_id, body.enabled))


@router.delete(
    "/segments/{segment_id}",
    summary="删除分段（kb:segment:update；ACL 可编辑；父块连同子块逻辑删除）",
    response_model=ApiResponse[None],
)
async def delete_segment(
    dataset_id: int, segment_id: int, request: Request, ctx: EditCtx, session: DbDep
) -> dict[str, Any]:
    await segment_service.delete_segment(session, ctx, request, dataset_id, segment_id)
    return ok()


@router.post(
    "/segments/{segment_id}/children",
    summary="新增子块（kb:segment:update；ACL 可编辑；仅父块）",
    response_model=ApiResponse[ChildChunkItem],
)
async def create_child(
    dataset_id: int, segment_id: int, body: ChildCreate, request: Request, ctx: EditCtx, session: DbDep
) -> dict[str, Any]:
    return ok(await segment_service.create_child(session, ctx, request, dataset_id, segment_id, body))


@router.put(
    "/child-chunks/{child_id}",
    summary="编辑子块（kb:segment:update；ACL 可编辑；异步重建索引）",
    response_model=ApiResponse[ChildChunkItem],
)
async def update_child(
    dataset_id: int, child_id: int, body: ChildUpdate, request: Request, ctx: EditCtx, session: DbDep
) -> dict[str, Any]:
    return ok(await segment_service.update_child(session, ctx, request, dataset_id, child_id, body))


@router.delete(
    "/child-chunks/{child_id}",
    summary="删除子块（kb:segment:update；ACL 可编辑）",
    response_model=ApiResponse[None],
)
async def delete_child(
    dataset_id: int, child_id: int, request: Request, ctx: EditCtx, session: DbDep
) -> dict[str, Any]:
    await segment_service.delete_child(session, ctx, request, dataset_id, child_id)
    return ok()
