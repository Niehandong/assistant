"""内部统计（5.9.4，供 iam 组织删除检查与用户影响提示）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.internal import CountResult
from app.services import internal_service
from platform_common.db import get_db
from platform_common.response import ApiResponse, ok

router = APIRouter(tags=["internal"])


@router.get(
    "/stats/datasets",
    summary="未删除知识库数（内部；dept_id 或 owner_id 二选一）",
    response_model=ApiResponse[CountResult],
)
async def dataset_stats(
    session: Annotated[AsyncSession, Depends(get_db)],
    dept_id: Annotated[int | None, Query(ge=1)] = None,
    owner_id: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    return ok(await internal_service.stats(session, dept_id, owner_id))
