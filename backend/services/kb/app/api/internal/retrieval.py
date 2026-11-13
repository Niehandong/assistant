"""内部检索接口（5.9.1）。鉴权由汇总路由的 ``require_internal`` 统一提供。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.internal import InternalRetrievalResult, InternalRetrieveBody
from app.services import internal_service
from platform_common.db import get_db
from platform_common.response import ApiResponse, ok

router = APIRouter(tags=["internal"])


@router.post(
    "/datasets/{dataset_id}/retrieve",
    summary="按用户身份检索（内部）",
    response_model=ApiResponse[InternalRetrievalResult],
)
async def retrieve(
    dataset_id: int, body: InternalRetrieveBody, session: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, Any]:
    return ok(await internal_service.retrieve(session, dataset_id, body))
