"""iam 对外接口汇总路由（前缀 /api/v1）。各业务路由在这里 include。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, logs, orgs, permissions, roles, users

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(orgs.router)
router.include_router(roles.router)
router.include_router(permissions.router)
router.include_router(users.router)
router.include_router(logs.router)
