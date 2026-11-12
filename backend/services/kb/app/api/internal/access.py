"""内部访问判定与知识库简要信息（5.9.2、5.9.3）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.internal import AccessibleBody, AccessibleResult, BriefBody, DatasetBrief
from app.services import internal_service
from platform_common.db import get_db
from platform_common.response import ApiResponse, ok

router = APIRouter(tags=["internal"])
DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/access/accessible-datasets",
    summary="用户当前可访问的知识库（内部，实时计算）",
    response_model=ApiResponse[AccessibleResult],
)
async def accessible_datasets(body: AccessibleBody, session: DbDep) -> dict[str, Any]:
    return ok(await internal_service.accessible_datasets(session, body))


@router.post(
    "/datasets/brief", summary="知识库简要信息（内部，含已删除）", response_model=ApiResponse[list[DatasetBrief]]
)
async def datasets_brief(body: BriefBody, session: DbDep) -> dict[str, Any]:
    return ok(await internal_service.briefs(session, body))
