"""内部接口：权限上下文（5.6.1、5.6.2）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.authz import BatchContextsRequest
from app.services import authz_service
from platform_common.db import get_db
from platform_common.errors import BizError, CommonErrors
from platform_common.response import ok

router = APIRouter(prefix="/authz", tags=["internal-authz"])
DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("/contexts/{user_id}", summary="计算并返回用户权限上下文（内部）")
async def get_context(user_id: int, session: DbDep) -> dict[str, Any]:
    ctx = await authz_service.get_context(session, user_id)
    if ctx is None:
        raise BizError(*CommonErrors.NOT_FOUND)
    return ok(ctx.model_dump(mode="json"))


@router.post("/contexts/batch", summary="批量获取权限上下文（内部，≤200）")
async def batch_contexts(body: BatchContextsRequest, session: DbDep) -> dict[str, Any]:
    result = await authz_service.get_contexts(session, body.user_ids)
    items = {str(uid): (c.model_dump(mode="json") if c else None) for uid, c in result.items()}
    return ok({"items": items})
