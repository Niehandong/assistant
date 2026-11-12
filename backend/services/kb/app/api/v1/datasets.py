"""知识库接口（tech-design-m2 5.2）：我的列表、选项、创建、详情、编辑、检索设置、删除。

自行转移 ``POST /datasets/{id}/transfer``（BE-23）。固定路径（``/options``）必须声明在 ``/{id}`` 之前。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.dataset_repo import DatasetFilter
from app.schemas.admin import TransferBody
from app.schemas.dataset import (
    DatasetCreate,
    DatasetDeleteBody,
    DatasetDetail,
    DatasetItem,
    DatasetOption,
    DatasetUpdate,
    RetrievalConfigUpdate,
)
from app.services import dataset_service, transfer_service
from platform_common.auth.context import AuthContext
from platform_common.auth.deps import require_perm
from platform_common.db import get_db
from platform_common.pagination import MAX_PAGE_SIZE, PageParams, PageParamsDep
from platform_common.response import ApiResponse, Page, ok, page

router = APIRouter(prefix="/kb/datasets", tags=["datasets"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
ListCtx = Annotated[AuthContext, Depends(require_perm("kb:dataset:list"))]
CreateCtx = Annotated[AuthContext, Depends(require_perm("kb:dataset:create"))]
UpdateCtx = Annotated[AuthContext, Depends(require_perm("kb:dataset:update"))]
TransferCtx = Annotated[AuthContext, Depends(require_perm("kb:dataset:transfer"))]
DeleteCtx = Annotated[AuthContext, Depends(require_perm("kb:dataset:delete"))]
OptionsCtx = Annotated[AuthContext, Depends(require_perm("kb:dataset:list", "openapi:apikey:manage", mode="any"))]


@router.get("", summary="我的知识库（kb:dataset:list；所有者 + 被分配）", response_model=ApiResponse[Page[DatasetItem]])
async def list_datasets(
    ctx: ListCtx,
    session: DbDep,
    pp: PageParamsDep,
    keyword: Annotated[str | None, Query(max_length=50)] = None,
    my_permission: Annotated[Literal["owner", "edit", "read"] | None, Query()] = None,
    owner_keyword: Annotated[str | None, Query(max_length=50)] = None,
    chunk_mode: Annotated[Literal["general", "parent_child", "unset"] | None, Query()] = None,
    only_owned: Annotated[bool, Query()] = False,
    sort_by: Annotated[Literal["updated_at", "name", "doc_count"], Query()] = "updated_at",
    sort_order: Annotated[Literal["asc", "desc"] | None, Query(description="默认 desc；name 默认 asc")] = None,
) -> dict[str, Any]:
    f = DatasetFilter(
        keyword=keyword.strip() if keyword else None,
        my_permission=my_permission,
        owner_keyword=owner_keyword.strip() if owner_keyword else None,
        chunk_mode=chunk_mode,
        only_owned=only_owned,
        sort_by=sort_by,
        sort_desc=(sort_order or ("asc" if sort_by == "name" else "desc")) == "desc",
    )
    items, total = await dataset_service.list_my_datasets(session, ctx, pp, f)
    return page(items, total, pp.page, pp.page_size)


@router.get(
    "/options",
    summary="可访问知识库选项（kb:dataset:list 或 openapi:apikey:manage）",
    response_model=ApiResponse[Page[DatasetOption]],
)
async def dataset_options(
    ctx: OptionsCtx,
    session: DbDep,
    keyword: Annotated[str | None, Query(max_length=50)] = None,
    page_no: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
) -> dict[str, Any]:
    pp = PageParams(page=page_no, page_size=page_size)
    items, total = await dataset_service.list_options(session, ctx, keyword.strip() if keyword else None, pp)
    return page(items, total, pp.page, pp.page_size)


@router.post("", summary="创建知识库（kb:dataset:create）", response_model=ApiResponse[DatasetDetail])
async def create_dataset(body: DatasetCreate, request: Request, session: DbDep, ctx: CreateCtx) -> dict[str, Any]:
    return ok(await dataset_service.create_dataset(session, ctx, request, body))


@router.get(
    "/{dataset_id}", summary="知识库详情（kb:dataset:list；ACL 只读）", response_model=ApiResponse[DatasetDetail]
)
async def get_dataset(dataset_id: int, ctx: ListCtx, session: DbDep) -> dict[str, Any]:
    return ok(await dataset_service.get_detail(session, ctx, dataset_id))


@router.put(
    "/{dataset_id}",
    summary="编辑基础信息（kb:dataset:update；ACL 可编辑；更换向量模型需所有者）",
    response_model=ApiResponse[DatasetDetail],
)
async def update_dataset(
    dataset_id: int, body: DatasetUpdate, request: Request, session: DbDep, ctx: UpdateCtx
) -> dict[str, Any]:
    return ok(await dataset_service.update_dataset(session, ctx, request, dataset_id, body))


@router.put(
    "/{dataset_id}/retrieval-config",
    summary="保存检索设置（kb:dataset:update；ACL 可编辑；返回最新详情）",
    response_model=ApiResponse[DatasetDetail],
)
async def update_retrieval_config(
    dataset_id: int, body: RetrievalConfigUpdate, request: Request, session: DbDep, ctx: UpdateCtx
) -> dict[str, Any]:
    return ok(await dataset_service.update_retrieval_config(session, ctx, request, dataset_id, body))


@router.delete(
    "/{dataset_id}",
    summary="删除知识库（kb:dataset:delete；ACL 所有者，超管放行；请求体 confirm_name）",
    response_model=ApiResponse[None],
)
async def delete_dataset(
    dataset_id: int,
    body: Annotated[DatasetDeleteBody, Body()],
    request: Request,
    session: DbDep,
    ctx: DeleteCtx,
) -> dict[str, Any]:
    await dataset_service.delete_dataset(session, ctx, request, dataset_id, body)
    return ok(None)


@router.post(
    "/{dataset_id}/transfer",
    summary="所有者自行转移（kb:dataset:transfer；ACL 所有者；接收人限本公司及下属）",
    response_model=ApiResponse[DatasetDetail],
)
async def transfer_dataset(
    dataset_id: int, body: TransferBody, request: Request, session: DbDep, ctx: TransferCtx
) -> dict[str, Any]:
    return ok(await transfer_service.owner_transfer(session, ctx, request, dataset_id, body))
