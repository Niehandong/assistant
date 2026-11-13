"""我的 API 密钥（tech-design-m3 5.1）。权限码 ``openapi:apikey:manage``，范围仅本人（created_by = 当前用户）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.api_key import (
    AccessibleDataset,
    ApiKeyBody,
    ApiKeyItem,
    ApiKeySecretResult,
    ApiKeyStatusBody,
    ApiKeyUpdateBody,
    KeyStatus,
    VersionBody,
)
from app.services import api_key_service
from platform_common.auth.context import AuthContext
from platform_common.auth.deps import require_perm
from platform_common.db import get_db
from platform_common.pagination import PageParamsDep
from platform_common.response import ApiResponse, Page, ok

router = APIRouter(prefix="/open-platform/api-keys", tags=["api-keys"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
Ctx = Annotated[AuthContext, Depends(require_perm("openapi:apikey:manage"))]


@router.get(
    "", summary="我的 API 密钥列表（openapi:apikey:manage；仅本人）", response_model=ApiResponse[Page[ApiKeyItem]]
)
async def list_keys(
    session: DbDep,
    ctx: Ctx,
    params: PageParamsDep,
    name: Annotated[str | None, Query(max_length=50, description="名称模糊")] = None,
    status: Annotated[KeyStatus | None, Query(description="计算后的状态")] = None,
) -> dict[str, Any]:
    return await api_key_service.list_keys(
        session, ctx, page_no=params.page, page_size=params.page_size, name=name, status=status
    )


@router.post(
    "",
    summary="创建 API 密钥（openapi:apikey:manage；明文只在本响应出现一次）",
    response_model=ApiResponse[ApiKeySecretResult],
)
async def create_key(body: ApiKeyBody, request: Request, session: DbDep, ctx: Ctx) -> dict[str, Any]:
    return ok(await api_key_service.create_key(session, ctx, request, body))


@router.get("/{key_id}", summary="密钥详情（openapi:apikey:manage；仅本人）", response_model=ApiResponse[ApiKeyItem])
async def get_key(key_id: int, session: DbDep, ctx: Ctx) -> dict[str, Any]:
    return ok(await api_key_service.get_key(session, ctx, key_id))


@router.put("/{key_id}", summary="编辑密钥（openapi:apikey:manage；仅本人）", response_model=ApiResponse[ApiKeyItem])
async def update_key(key_id: int, body: ApiKeyUpdateBody, request: Request, session: DbDep, ctx: Ctx) -> dict[str, Any]:
    return ok(await api_key_service.update_key(session, ctx, request, key_id, body))


@router.put(
    "/{key_id}/status", summary="启用/停用密钥（openapi:apikey:manage；仅本人）", response_model=ApiResponse[ApiKeyItem]
)
async def set_status(key_id: int, body: ApiKeyStatusBody, request: Request, session: DbDep, ctx: Ctx) -> dict[str, Any]:
    return ok(await api_key_service.set_status(session, ctx, request, key_id, body))


@router.post(
    "/{key_id}/regenerate",
    summary="重新生成密钥（openapi:apikey:manage；仅本人；明文只在本响应出现一次）",
    response_model=ApiResponse[ApiKeySecretResult],
)
async def regenerate(key_id: int, body: VersionBody, request: Request, session: DbDep, ctx: Ctx) -> dict[str, Any]:
    return ok(await api_key_service.regenerate(session, ctx, request, key_id, body))


@router.delete("/{key_id}", summary="删除密钥（openapi:apikey:manage；仅本人）", response_model=ApiResponse[None])
async def delete_key(key_id: int, request: Request, session: DbDep, ctx: Ctx) -> dict[str, Any]:
    await api_key_service.delete_key(session, ctx, request, key_id)
    return ok(None)


@router.get(
    "/{key_id}/accessible-datasets",
    summary="当前可检索的知识库名单（openapi:apikey:manage；仅本人）",
    response_model=ApiResponse[list[AccessibleDataset]],
)
async def accessible_datasets(key_id: int, session: DbDep, ctx: Ctx) -> dict[str, Any]:
    return ok(await api_key_service.accessible_datasets(session, ctx, key_id))
