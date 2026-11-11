"""权限点接口（5.4.9）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.permission import PermissionTreeData
from app.services import role_service
from platform_common.auth.context import AuthContext
from platform_common.auth.deps import require_perm
from platform_common.db import get_db
from platform_common.response import ApiResponse, ok

router = APIRouter(prefix="/system/permissions", tags=["permissions"])


@router.get("/tree", summary="权限树（system:role:list）", response_model=ApiResponse[PermissionTreeData])
async def permission_tree(
    ctx: Annotated[AuthContext, Depends(require_perm("system:role:list"))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    return ok(await role_service.permission_tree(session, ctx))
