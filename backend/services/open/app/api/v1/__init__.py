"""open 对外接口汇总路由（前缀 /api/v1）。含审计（BE-26）与开放检索（BE-27）。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import api_keys, audit, call_logs, open_retrieve

router = APIRouter(prefix="/api/v1")
router.include_router(api_keys.router)
router.include_router(call_logs.router)
router.include_router(audit.router)
router.include_router(open_retrieve.router)
