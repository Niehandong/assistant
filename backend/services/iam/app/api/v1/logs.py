"""日志接口（5.5）：只读，无修改/删除路由。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.log import LoginLogItem, OperationLogDetail, OperationLogItem
from app.services import log_service
from platform_common.auth.context import AuthContext
from platform_common.auth.deps import require_perm
from platform_common.db import get_db
from platform_common.pagination import PageParamsDep
from platform_common.response import ApiResponse, Page, ok, page

router = APIRouter(prefix="/system", tags=["logs"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
OplogCtx = Annotated[AuthContext, Depends(require_perm("system:oplog:list"))]
LoginlogCtx = Annotated[AuthContext, Depends(require_perm("system:loginlog:list"))]


@router.get(
    "/operation-logs",
    summary="操作日志列表（system:oplog:list）",
    response_model=ApiResponse[Page[OperationLogItem]],
)
async def list_operation_logs(
    ctx: OplogCtx,
    session: DbDep,
    pp: PageParamsDep,
    start_time: Annotated[datetime, Query(description="开始时间（必填）")],
    end_time: Annotated[datetime, Query(description="结束时间（必填，跨度 ≤180 天）")],
    operator: Annotated[str | None, Query(max_length=32, description="操作人姓名或账号（模糊）")] = None,
    module: Annotated[str | None, Query(max_length=32)] = None,
    action: Annotated[str | None, Query(max_length=32)] = None,
    result: Annotated[str | None, Query(pattern="^(success|failure)$")] = None,
) -> dict[str, Any]:
    items, total = await log_service.list_operation_logs(
        session,
        ctx,
        pp,
        start_time=start_time,
        end_time=end_time,
        operator=operator,
        module=module,
        action=action,
        result=result,
    )
    return page(items, total, pp.page, pp.page_size)


@router.get(
    "/operation-logs/{log_id}",
    summary="操作日志详情（system:oplog:list）",
    response_model=ApiResponse[OperationLogDetail],
)
async def get_operation_log(log_id: int, ctx: OplogCtx, session: DbDep) -> dict[str, Any]:
    return ok(await log_service.get_operation_log(session, ctx, log_id))


@router.get(
    "/login-logs",
    summary="登录日志列表（system:loginlog:list）",
    response_model=ApiResponse[Page[LoginLogItem]],
)
async def list_login_logs(
    ctx: LoginlogCtx,
    session: DbDep,
    pp: PageParamsDep,
    start_time: Annotated[datetime, Query(description="开始时间（必填）")],
    end_time: Annotated[datetime, Query(description="结束时间（必填，跨度 ≤180 天）")],
    username: Annotated[str | None, Query(max_length=64, description="账号（模糊）")] = None,
    result: Annotated[str | None, Query(pattern="^(success|failure)$")] = None,
    ip: Annotated[str | None, Query(max_length=64)] = None,
) -> dict[str, Any]:
    items, total = await log_service.list_login_logs(
        session, ctx, pp, start_time=start_time, end_time=end_time, username=username, result=result, ip=ip
    )
    return page(items, total, pp.page, pp.page_size)
