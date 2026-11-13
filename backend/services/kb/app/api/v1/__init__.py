"""kb 对外接口汇总路由（前缀 /api/v1）。各业务路由由后续任务在这里 include。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import admin, assignments, datasets, documents, models, retrieval, segments, uploads

router = APIRouter(prefix="/api/v1")
router.include_router(models.router)
router.include_router(admin.router)
router.include_router(datasets.router)
router.include_router(assignments.router)
router.include_router(uploads.router)
router.include_router(documents.router)
router.include_router(segments.router)
router.include_router(retrieval.router)
