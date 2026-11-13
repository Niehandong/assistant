"""调用日志保留期清理（tech-design-m3 3.4）：每日分批物理删除超过 ``CALL_LOG_RETENTION_DAYS`` 的记录。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.core.config import Settings, get_settings
from app.repositories import call_log_repo
from platform_common.db import get_session_factory
from platform_common.jobs import run_periodic

logger = logging.getLogger(__name__)


async def cleanup_call_logs(settings: Settings | None = None, *, now: datetime | None = None) -> int:
    """分批删除（每批独立提交，避免长事务与大锁），返回总删除行数。"""
    s = settings or get_settings()
    cutoff = (now or datetime.now().astimezone()) - timedelta(days=s.CALL_LOG_RETENTION_DAYS)
    total = 0
    while True:
        async with get_session_factory()() as session:
            n = await call_log_repo.delete_expired_batch(session, cutoff, s.CALL_LOG_CLEANUP_BATCH)
            await session.commit()
        total += n
        if n < s.CALL_LOG_CLEANUP_BATCH:
            break
    if total:
        logger.info("调用日志清理完成", extra={"deleted": total, "cutoff": cutoff.isoformat()})
    return total


async def run_cleanup(settings: Settings | None = None) -> None:
    s = settings or get_settings()
    await run_periodic("open_call_log_cleanup", s.CALL_LOG_CLEANUP_INTERVAL_SECONDS, lambda: _once(s))


async def _once(settings: Settings) -> None:
    await cleanup_call_logs(settings)
