"""日志查询与操作日志入库（BE-10）。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import log_repo
from app.schemas.log import LoginLogItem, OperationLogDetail, OperationLogItem
from platform_common.auth.context import AuthContext
from platform_common.db import get_session_factory
from platform_common.errors import BizError, CommonErrors
from platform_common.oplog import OpLogEvent, mask_sensitive
from platform_common.pagination import PageParams
from platform_common.response import LOCAL_TZ

logger = logging.getLogger(__name__)

MAX_RANGE = timedelta(days=180)


def _cut(value: str | None, size: int) -> str | None:
    return value[:size] if value is not None else None


def normalize_range(start_time: datetime, end_time: datetime) -> tuple[datetime, datetime]:
    """无时区的时间按东八区解释；end < start 或跨度 > 180 天抛 400001。"""
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=LOCAL_TZ)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=LOCAL_TZ)
    if end_time < start_time:
        raise BizError(CommonErrors.INVALID_PARAMS[0], "结束时间不能早于开始时间")
    if end_time - start_time > MAX_RANGE:
        raise BizError(CommonErrors.INVALID_PARAMS[0], "查询时间跨度不能超过 180 天")
    return start_time, end_time


# --------------------------------------------------------------------------- 入库（Stream 消费）


async def ingest_oplog(data: dict[str, Any]) -> bool:
    """消费一条 OpLogEvent；event_id 冲突忽略。校验失败抛异常（由消费者重试后进死信）。"""
    event = OpLogEvent.model_validate(data)
    event_id = uuid.UUID(event.event_id)
    async with get_session_factory()() as session:
        company_name = await log_repo.get_org_name(session, event.company_id) if event.company_id else None
        inserted = await log_repo.insert_operation_log(
            session,
            {
                "event_id": event_id,
                "service": event.service[:16],
                "operator_id": event.operator_id,
                "operator_username": event.operator_username[:32],
                "operator_name": event.operator_name[:30],
                "company_id": event.company_id,
                "dept_id": event.dept_id,
                "company_name": _cut(company_name, 50),
                "module": event.module[:32],
                "action": event.action[:32],
                "target_type": event.target_type[:32],
                "target_id": _cut(event.target_id, 64),
                "target_name": _cut(event.target_name, 200),
                "summary": mask_sensitive(event.summary),  # 入库端兜底脱敏（不信任发送端）
                "result": event.result,
                "error_message": _cut(event.error_message, 500),
                "ip": _cut(event.ip, 64),
                "user_agent": _cut(event.user_agent, 500),
                "request_id": _cut(event.request_id, 64),
                "occurred_at": event.occurred_at,
                "created_by": event.operator_id,
                "updated_by": event.operator_id,
            },
        )
        await session.commit()
    return inserted


async def handle_oplog_message(data: dict[str, Any]) -> None:
    await ingest_oplog(data)


# --------------------------------------------------------------------------- 查询


async def list_operation_logs(
    session: AsyncSession,
    ctx: AuthContext,
    pp: PageParams,
    *,
    start_time: datetime,
    end_time: datetime,
    operator: str | None,
    module: str | None,
    action: str | None,
    result: str | None,
) -> tuple[list[OperationLogItem], int]:
    start_time, end_time = normalize_range(start_time, end_time)
    rows, total = await log_repo.page_operation_logs(
        session,
        ctx,
        offset=pp.offset,
        limit=pp.limit,
        start_time=start_time,
        end_time=end_time,
        operator=operator,
        module=module,
        action=action,
        result=result,
    )
    return [OperationLogItem.model_validate(r) for r in rows], total


async def get_operation_log(session: AsyncSession, ctx: AuthContext, log_id: int) -> OperationLogDetail:
    row = await log_repo.get_operation_log(session, ctx, log_id)
    if row is None:
        raise BizError(*CommonErrors.NOT_FOUND)
    return OperationLogDetail.model_validate(row)


async def list_login_logs(
    session: AsyncSession,
    ctx: AuthContext,
    pp: PageParams,
    *,
    start_time: datetime,
    end_time: datetime,
    username: str | None,
    result: str | None,
    ip: str | None,
) -> tuple[list[LoginLogItem], int]:
    start_time, end_time = normalize_range(start_time, end_time)
    rows, total = await log_repo.page_login_logs(
        session,
        ctx,
        offset=pp.offset,
        limit=pp.limit,
        start_time=start_time,
        end_time=end_time,
        username=username,
        result=result,
        ip=ip,
    )
    items = [
        LoginLogItem(
            id=r.id,
            login_at=r.login_at,
            username=r.username,
            user_id=r.user_id,
            user_name=user_name,
            company_name=company_name,
            result=r.result,
            fail_reason=r.fail_reason,
            fail_message=r.fail_message,
            ip=r.ip,
            user_agent=r.user_agent,
        )
        for r, user_name, company_name in rows
    ]
    return items, total
