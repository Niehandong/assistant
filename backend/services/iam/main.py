"""iam 服务入口：``cd backend/services/iam && ../../../.venv/bin/python main.py``（无热加载，改代码需重启）。"""

from __future__ import annotations

import uvicorn

from app import jobs
from app.api.internal import router as internal_router
from app.api.v1 import router as api_v1_router
from app.core.config import get_settings
from app.services import authz_service, downstream
from platform_common.app_factory import create_app

settings = get_settings()
app = create_app(
    settings,
    routers=[api_v1_router, internal_router],
    lifespan_hooks=[authz_service.lifespan_hook, downstream.lifespan_hook, jobs.lifespan_hook],
    title="iam 认证与权限服务",
)

if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=False, proxy_headers=False)
