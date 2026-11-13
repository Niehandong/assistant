"""API 密钥审计（tech-design-m3 5.3）。权限码 ``openapi:apikey:audit``，按数据范围过滤；没有编辑/启用/重新生成。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.api_key import VersionBody
from app.schemas.audit import AuditApiKeyItem, AuditCapabilities, AuditStatus
from app.schemas.call_log import AuditCallLogItem, CallResult
from app.services import audit_service
from platform_common.auth.context import AuthContext
from platform_common.auth.deps import require_perm
from platform_common.db import get_db
from platform_common.pagination import PageParamsDep
from platform_common.response import ApiResponse, Page, ok

router = APIRouter(prefix="/open-platform/audit", tags=["audit"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
Ctx = Annotated[AuthContext, Depends(require_perm("openapi:apikey:audit"))]


@router.get(
    "/api-keys",
    summary="API 密钥审计列表（openapi:apikey:audit；按数据范围）",
    response_model=ApiResponse[Page[AuditApiKeyItem]],
)
async def list_keys(
    session: DbDep,
    ctx: Ctx,
    params: PageParamsDep,
    creator_keyword: Annotated[str | None, Query(max_length=64, description="创建人姓名/账号")] = None,
    org_id: Annotated[int | None, Query(ge=1, description="所属组织（含下级）")] = None,
    status: Annotated[AuditStatus | None, Query()] = None,
) -> dict[str, Any]:
    return await audit_service.list_keys(
        session, ctx, params, creator_keyword=creator_keyword, org_id=org_id, status=status
    )


@router.put(
    "/api-keys/{key_id}/disable",
    summary="管理员停用密钥（openapi:apikey:audit；终态，已停用则幂等）",
    response_model=ApiResponse[AuditApiKeyItem],
)
async def disable_key(key_id: int, body: VersionBody, request: Request, session: DbDep, ctx: Ctx) -> dict[str, Any]:
    return ok(await audit_service.disable_key(session, ctx, request, key_id, body.version))


@router.delete("/api-keys/{key_id}", summary="管理员删除密钥（openapi:apikey:audit）", response_model=ApiResponse[None])
async def delete_key(key_id: int, request: Request, session: DbDep, ctx: Ctx) -> dict[str, Any]:
    await audit_service.delete_key(session, ctx, request, key_id)
    return ok(None)


@router.get(
    "/call-logs",
    summary="调用日志审计（openapi:apikey:audit；按数据范围）",
    response_model=ApiResponse[Page[AuditCallLogItem]],
)
async def list_call_logs(
    session: DbDep,
    ctx: Ctx,
    params: PageParamsDep,
    start_time: Annotated[datetime | None, Query(description="默认近 7 天")] = None,
    end_time: Annotated[datetime | None, Query(description="默认当前时间；跨度 ≤ 90 天（400604）")] = None,
    api_key_id: Annotated[int | None, Query(ge=1)] = None,
    dataset_id: Annotated[int | None, Query(ge=1)] = None,
    result: Annotated[CallResult | None, Query()] = None,
    creator_keyword: Annotated[str | None, Query(max_length=64)] = None,
    include_unknown: Annotated[
        bool, Query(description="含无法识别密钥的调用；仅超管/ALL 范围生效，否则静默忽略")
    ] = False,
) -> dict[str, Any]:
    return await audit_service.list_call_logs(
        session,
        ctx,
        params,
        start_time=start_time,
        end_time=end_time,
        api_key_id=api_key_id,
        dataset_id=dataset_id,
        result=result,
        creator_keyword=creator_keyword,
        include_unknown=include_unknown,
    )


@router.get(
    "/capabilities",
    summary="审计能力标记（openapi:apikey:audit；不按数据范围）",
    response_model=ApiResponse[AuditCapabilities],
)
async def capabilities(ctx: Ctx) -> dict[str, Any]:
    return ok(audit_service.capabilities(ctx))
