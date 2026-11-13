"""内部接口：用户/组织增量同步（5.6.3、5.6.4）。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import sync_service
from platform_common.db import get_db
from platform_common.response import ok

router = APIRouter(prefix="/sync", tags=["internal-sync"])
DbDep = Annotated[AsyncSession, Depends(get_db)]
UpdatedAfter = Annotated[datetime | None, Query(description="ISO 时间，可选")]
AfterId = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=1000)]


@router.get("/users", summary="用户增量同步（含已删除）")
async def sync_users(
    session: DbDep, updated_after: UpdatedAfter = None, after_id: AfterId = 0, limit: Limit = 500
) -> dict[str, Any]:
    page = await sync_service.sync_users(session, updated_after, after_id, limit)
    return ok(page.model_dump(mode="json"))


@router.get("/orgs", summary="组织增量同步（含已删除）")
async def sync_orgs(
    session: DbDep, updated_after: UpdatedAfter = None, after_id: AfterId = 0, limit: Limit = 500
) -> dict[str, Any]:
    page = await sync_service.sync_orgs(session, updated_after, after_id, limit)
    return ok(page.model_dump(mode="json"))
