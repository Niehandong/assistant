"""后台任务：操作日志消费者、日志保留期清理，由 lifespan 钩子启动。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from platform_common.jobs import run_periodic

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan_hook(_app: FastAPI) -> AsyncIterator[None]:
    """启动操作日志消费者与清理任务；退出时优雅停止。LOG_JOBS_ENABLED=false 时不启动（测试用）。"""
    if not get_settings().LOG_JOBS_ENABLED:
        yield
        return
    from app.jobs.log_cleanup import scheduled_cleanup
    from app.jobs.oplog_consumer import build_consumer

    consumer = build_consumer()
    tasks = [
        asyncio.create_task(consumer.run_forever(), name="oplog-consumer"),
        asyncio.create_task(run_periodic("iam-log-cleanup", 3600, scheduled_cleanup), name="log-cleanup"),
    ]
    try:
        yield
    finally:
        await consumer.stop()
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
