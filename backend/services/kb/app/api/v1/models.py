"""模型配置接口（tech-design-m2 5.1）。路由层只收参、声明权限、调 service。"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.model import (
    ModelCreate,
    ModelDefaultBody,
    ModelItem,
    ModelOption,
    ModelStatusBody,
    ModelTestBody,
    ModelTestResult,
    ModelUpdate,
)
from app.services import model_service
from platform_common.auth.context import AuthContext
from platform_common.auth.deps import require_perm
from platform_common.db import get_db
from platform_common.pagination import PageParamsDep
from platform_common.response import ApiResponse, Page, ok, page

router = APIRouter(prefix="/kb/models", tags=["models"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
ListCtx = Annotated[AuthContext, Depends(require_perm("system:model:list"))]
CreateCtx = Annotated[AuthContext, Depends(require_perm("system:model:create"))]
UpdateCtx = Annotated[AuthContext, Depends(require_perm("system:model:update"))]
DeleteCtx = Annotated[AuthContext, Depends(require_perm("system:model:delete"))]
TestCtx = Annotated[AuthContext, Depends(require_perm("system:model:create", "system:model:update", mode="any"))]
OptionsCtx = Annotated[AuthContext, Depends(require_perm("kb:dataset:list", "kb:dataset:create", mode="any"))]


@router.get("", summary="模型列表（system:model:list）", response_model=ApiResponse[Page[ModelItem]])
async def list_models(
    ctx: ListCtx,
    session: DbDep,
    pp: PageParamsDep,
    model_type: Annotated[Literal["embedding", "rerank"] | None, Query()] = None,
    status: Annotated[Literal["enabled", "disabled"] | None, Query()] = None,
    keyword: Annotated[str | None, Query(max_length=50)] = None,
) -> dict[str, Any]:
    items, total = await model_service.list_models(session, pp, model_type=model_type, status=status, keyword=keyword)
    return page(items, total, pp.page, pp.page_size)


@router.get(
    "/options",
    summary="可选模型（kb:dataset:list 或 kb:dataset:create；仅启用模型，不含地址与凭据）",
    response_model=ApiResponse[list[ModelOption]],
)
async def model_options(
    ctx: OptionsCtx, session: DbDep, model_type: Annotated[Literal["embedding", "rerank"], Query()]
) -> dict[str, Any]:
    return ok(await model_service.list_options(session, model_type))


@router.post(
    "/test",
    summary="测试模型连接（system:model:create 或 system:model:update；失败以 success=false 返回）",
    response_model=ApiResponse[ModelTestResult],
)
async def test_model(body: ModelTestBody, ctx: TestCtx, session: DbDep) -> dict[str, Any]:
    return ok(await model_service.test_endpoint(session, body))


@router.post("", summary="新增模型（system:model:create）", response_model=ApiResponse[ModelItem])
async def create_model(body: ModelCreate, request: Request, session: DbDep, ctx: CreateCtx) -> dict[str, Any]:
    return ok(await model_service.create_model(session, ctx, request, body))


@router.put("/{model_id}", summary="编辑模型（system:model:update）", response_model=ApiResponse[ModelItem])
async def update_model(
    model_id: int, body: ModelUpdate, request: Request, session: DbDep, ctx: UpdateCtx
) -> dict[str, Any]:
    return ok(await model_service.update_model(session, ctx, request, model_id, body))


@router.put("/{model_id}/status", summary="启用/停用模型（system:model:update）", response_model=ApiResponse[ModelItem])
async def set_status(
    model_id: int, body: ModelStatusBody, request: Request, session: DbDep, ctx: UpdateCtx
) -> dict[str, Any]:
    return ok(await model_service.set_status(session, ctx, request, model_id, body))


@router.put("/{model_id}/default", summary="设为默认模型（system:model:update）", response_model=ApiResponse[ModelItem])
async def set_default(
    model_id: int, body: ModelDefaultBody, request: Request, session: DbDep, ctx: UpdateCtx
) -> dict[str, Any]:
    return ok(await model_service.set_default(session, ctx, request, model_id, body))


@router.delete("/{model_id}", summary="删除模型（system:model:delete）", response_model=ApiResponse[None])
async def delete_model(model_id: int, request: Request, session: DbDep, ctx: DeleteCtx) -> dict[str, Any]:
    await model_service.delete_model(session, ctx, request, model_id)
    return ok(None)
