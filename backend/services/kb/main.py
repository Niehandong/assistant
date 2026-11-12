"""kb 服务入口：``cd backend/services/kb && ../../../.venv/bin/python main.py``（无热加载，改代码需重启）。

BE-11 仅提供骨架（健康检查、OpenAPI）；业务路由由后续任务在 ``app.api.v1`` / ``app.api.internal`` 中追加。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.api.internal import router as internal_router
from app.api.v1 import router as api_v1_router
from app.core.config import get_settings
from app.parsers.registry import get_pool, shutdown_pool
from platform_common.app_factory import create_app

settings = get_settings()


@asynccontextmanager
async def parse_pool_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """解析进程池随应用创建/关闭（池大小 PARSE_PROCESS_WORKERS 同时限制并发解析数）。"""
    get_pool(settings.PARSE_PROCESS_WORKERS)
    try:
        yield
    finally:
        shutdown_pool()


app = create_app(
    settings,
    routers=[api_v1_router, internal_router],
    lifespan_hooks=[parse_pool_lifespan],
    title="kb 知识库服务",
)

if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=False)
