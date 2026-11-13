"""调用日志查询（BE-28，tech-design-m3 5.2）。

审计（BE-26）复用 ``resolve_time_range`` / ``to_item`` / ``call_log_repo``。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.constants import DEFAULT_LOG_SPAN_DAYS, MAX_LOG_SPAN_DAYS, OpenErrors
from app.models import ApiCallLog
from app.repositories import call_log_repo
from app.schemas.call_log import CallLogItem, LogDatasetRef, LogKeyRef
from platform_common.auth.context import AuthContext
from platform_common.errors import BizError, CommonErrors
from platform_common.pagination import PageParams
from platform_common.response import page

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=LOCAL_TZ) if value.tzinfo is None else value


def resolve_time_range(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    """默认近 7 天；跨度 ≤ 90 天（400604）；开始晚于结束 → 400001。"""
    end_t = _aware(end) if end else datetime.now().astimezone()
    start_t = _aware(start) if start else end_t - timedelta(days=DEFAULT_LOG_SPAN_DAYS)
    if start_t > end_t:
        code, message = CommonErrors.INVALID_PARAMS
        raise BizError(code, message, {"errors": [{"field": "start_time", "message": "开始时间不能晚于结束时间"}]})
    if end_t - start_t > timedelta(days=MAX_LOG_SPAN_DAYS):
        raise BizError(*OpenErrors.LOG_RANGE_TOO_LONG)
    return start_t, end_t


def to_item(row: ApiCallLog) -> CallLogItem:
    """api_call_log → 响应项。密钥名称/前缀取调用时的快照（密钥删除、改名后仍可追溯）。"""
    api_key = (
        LogKeyRef(id=row.api_key_id, name=row.key_name or "", key_masked=security.mask_key(row.key_prefix or ""))
        if row.api_key_id is not None
        else None
    )
    dataset = LogDatasetRef(id=row.dataset_id, name=row.dataset_name) if row.dataset_id is not None else None
    return CallLogItem(
        id=row.id,
        called_at=row.called_at,
        request_id=row.request_id,
        api_key=api_key,
        dataset=dataset,
        query=row.query,
        result_count=row.result_count,
        latency_ms=row.latency_ms,
        result=row.result,  # type: ignore[arg-type]
        error_code=row.error_code,
        client_ip=row.client_ip,
    )


async def list_my_logs(
    session: AsyncSession,
    ctx: AuthContext,
    params: PageParams,
    *,
    start_time: datetime | None,
    end_time: datetime | None,
    api_key_id: int | None,
    dataset_id: int | None,
    result: str | None,
) -> dict[str, Any]:
    """本人密钥的调用日志：``created_by = 当前用户``（含已删除密钥的日志），他人日志不可见。"""
    start, end = resolve_time_range(start_time, end_time)
    f = call_log_repo.CallLogFilter(
        start_time=start,
        end_time=end,
        api_key_id=api_key_id,
        dataset_id=dataset_id,
        result=result,
        owner_id=ctx.user_id,
    )
    rows, total = await call_log_repo.page_logs(session, f, offset=params.offset, limit=params.limit)
    return page([to_item(r) for r in rows], total, params.page, params.page_size)
