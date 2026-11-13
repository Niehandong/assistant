"""我的调用日志（tech-design-m3 5.2.1）。权限码 ``openapi:log:list``，范围 ``created_by = 当前用户``。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.call_log import CallLogItem, CallResult
from app.services import call_log_service
from platform_common.auth.context import AuthContext
from platform_common.auth.deps import require_perm
from platform_common.db import get_db
from platform_common.pagination import PageParamsDep
from platform_common.response import ApiResponse, Page

router = APIRouter(prefix="/open-platform/call-logs", tags=["call-logs"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
Ctx = Annotated[AuthContext, Depends(require_perm("openapi:log:list"))]


@router.get("", summary="我的调用日志（openapi:log:list；仅本人密钥）", response_model=ApiResponse[Page[CallLogItem]])
async def list_call_logs(
    session: DbDep,
    ctx: Ctx,
    params: PageParamsDep,
    start_time: Annotated[datetime | None, Query(description="默认近 7 天")] = None,
    end_time: Annotated[datetime | None, Query(description="默认当前时间；跨度 ≤ 90 天（400604）")] = None,
    api_key_id: Annotated[int | None, Query(ge=1)] = None,
    dataset_id: Annotated[int | None, Query(ge=1)] = None,
    result: Annotated[CallResult | None, Query()] = None,
) -> dict[str, Any]:
    return await call_log_service.list_my_logs(
        session,
        ctx,
        params,
        start_time=start_time,
        end_time=end_time,
        api_key_id=api_key_id,
        dataset_id=dataset_id,
        result=result,
    )
