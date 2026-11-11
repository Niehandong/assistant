"""日志保留期清理：每小时检查，东八区 03 点时分批物理删除超期日志。"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.models import SysLoginLog, SysOperationLog
from app.repositories import log_repo
from platform_common.db import get_session_factory
from platform_common.response import LOCAL_TZ

logger = logging.getLogger(__name__)

CLEANUP_HOUR = 3


async def cleanup_expired_logs(now: datetime | None = None, retention_days: int | None = None) -> dict[str, int]:
    """分批（每批 5000）删除保留期之前的登录/操作日志，返回各表删除数。"""
    now = now or datetime.now(UTC)
    days = retention_days if retention_days is not None else get_settings().LOG_RETENTION_DAYS
    cutoff = now - timedelta(days=days)
    deleted: dict[str, int] = {}
    for name, model in (("login_log", SysLoginLog), ("operation_log", SysOperationLog)):
        total = 0
        while True:
            async with get_session_factory()() as session:
                n = await log_repo.delete_older_than(session, model, cutoff)
                await session.commit()
            total += n
            if n < log_repo.OPLOG_BATCH_DELETE:
                break
            await asyncio.sleep(0)
        deleted[name] = total
    logger.info("日志保留期清理完成", extra={"deleted": deleted, "cutoff": cutoff.isoformat()})
    return deleted


async def scheduled_cleanup() -> None:
    """run_periodic 每小时调用一次；仅在东八区 03 点执行。"""
    if datetime.now(LOCAL_TZ).hour != CLEANUP_HOUR:
        return
    await cleanup_expired_logs()
