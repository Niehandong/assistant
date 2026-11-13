"""内部统计（5.5，供 iam 用户影响提示）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.api_key import KeyCount
from app.services import api_key_service
from platform_common.db import get_db
from platform_common.response import ApiResponse, ok

router = APIRouter(tags=["internal"])


@router.get("/stats/api-keys", summary="用户未删除的 API 密钥数（内部）", response_model=ApiResponse[KeyCount])
async def api_key_stats(
    session: Annotated[AsyncSession, Depends(get_db)], user_id: Annotated[int, Query(ge=1)]
) -> dict[str, Any]:
    return ok(await api_key_service.count_for_user(session, user_id))
