"""open 服务入口：``cd backend/services/open && ../../../.venv/bin/python main.py``（无热加载，改代码需重启）。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.api.internal import router as internal_router
from app.api.open_envelope import OpenEnvelopeMiddleware
from app.api.v1 import router as api_v1_router
from app.core.config import get_settings
from app.jobs import call_log_consumer, cleanup, ref_sync
from app.services.kb_client import close_kb_client
from platform_common.app_factory import create_app

settings = get_settings()


@asynccontextmanager
async def kb_client_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await close_kb_client()


@asynccontextmanager
async def background_jobs_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """进程内后台任务：iam 事件消费、副本对账、调用日志清理与入库（open-calllog）。多实例安全。"""
    if not settings.BACKGROUND_JOBS_ENABLED:
        yield
        return
    tasks = [
        asyncio.create_task(ref_sync.run_event_consumer(), name="ref-sync-consumer"),
        asyncio.create_task(ref_sync.run_reconcile(settings), name="ref-reconcile"),
        asyncio.create_task(cleanup.run_cleanup(settings), name="call-log-cleanup"),
        asyncio.create_task(call_log_consumer.run_call_log_consumer(), name="call-log-consumer"),
    ]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*tasks, return_exceptions=True)


app = create_app(
    settings,
    routers=[api_v1_router, internal_router],
    lifespan_hooks=[kb_client_lifespan, background_jobs_lifespan],
    title="open 开放平台服务",
)
# httpx 默认每个请求输出一行 INFO；开放检索是热路径（每次调用转发 kb），访问日志已覆盖，故降为 WARNING
logging.getLogger("httpx").setLevel(logging.WARNING)

# 最外层：开放检索前缀的统一错误信封（补齐 error_type / request_id，兜底写调用日志）
app.add_middleware(OpenEnvelopeMiddleware, settings=settings)

if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=False)
