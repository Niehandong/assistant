"""open 内部接口汇总路由（前缀 /internal/v1，统一依赖 require_internal，不经网关对外暴露）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.internal import stats
from platform_common.auth.internal import require_internal

router = APIRouter(prefix="/internal/v1", dependencies=[Depends(require_internal)])
router.include_router(stats.router)
