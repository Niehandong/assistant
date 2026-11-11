"""组织接口（5.2.1 ~ 5.2.8）。路由层只收参、声明权限、调 service。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.org import OrgCreate, OrgMove, OrgNode, OrgOption, OrgStatusBody, OrgUpdate
from app.services import org_service
from platform_common.auth.context import AuthContext
from platform_common.auth.deps import require_perm
from platform_common.db import get_db
from platform_common.errors import BizError, CommonErrors
from platform_common.response import ApiResponse, ok

router = APIRouter(prefix="/system/orgs", tags=["orgs"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
ListCtx = Annotated[AuthContext, Depends(require_perm("system:org:list"))]
UpdateCtx = Annotated[AuthContext, Depends(require_perm("system:org:update"))]
# 选择器：任一使用组织选择器的页面权限即可（5.2.2）
OPTIONS_PERMS = (
    "system:org:list",
    "system:user:list",
    "system:role:list",
    "system:oplog:list",
    "system:loginlog:list",
    "kb:admin:list",
    "openapi:apikey:audit",
)
OptionsCtx = Annotated[AuthContext, Depends(require_perm(*OPTIONS_PERMS, mode="any"))]


@router.get("/tree", summary="组织管理树（system:org:list）", response_model=ApiResponse[list[OrgNode]])
async def org_tree(
    ctx: ListCtx,
    session: DbDep,
    name: Annotated[str | None, Query(max_length=50)] = None,
    status: Annotated[str | None, Query(pattern="^(enabled|disabled)$")] = None,
) -> dict[str, Any]:
    return ok(await org_service.tree(session, ctx, name=name, status=status))


@router.get(
    "/options",
    summary="组织选择器（任一组织选择器相关页面权限）",
    response_model=ApiResponse[list[OrgOption]],
)
async def org_options(
    ctx: OptionsCtx,
    session: DbDep,
    types: Annotated[str | None, Query(description="逗号分隔：group,company,dept")] = None,
    include_disabled: Annotated[bool, Query()] = True,
) -> dict[str, Any]:
    type_set: set[str] | None = None
    if types:
        type_set = {t.strip() for t in types.split(",") if t.strip()}
        if not type_set <= {"group", "company", "dept"}:
            raise BizError(CommonErrors.INVALID_PARAMS[0], "types 取值不合法")
    return ok(await org_service.options(session, ctx, types=type_set, include_disabled=include_disabled))


@router.get("/{org_id}", summary="组织详情（system:org:list）", response_model=ApiResponse[OrgNode])
async def get_org(org_id: int, ctx: ListCtx, session: DbDep) -> dict[str, Any]:
    return ok(await org_service.get_org(session, ctx, org_id))


@router.post("", summary="新增组织（system:org:create）", response_model=ApiResponse[OrgNode])
async def create_org(
    body: OrgCreate,
    request: Request,
    session: DbDep,
    ctx: Annotated[AuthContext, Depends(require_perm("system:org:create"))],
) -> dict[str, Any]:
    return ok(await org_service.create_org(session, ctx, request, body))


@router.put("/{org_id}", summary="编辑组织（system:org:update）", response_model=ApiResponse[OrgNode])
async def update_org(org_id: int, body: OrgUpdate, request: Request, session: DbDep, ctx: UpdateCtx) -> dict[str, Any]:
    return ok(await org_service.update_org(session, ctx, request, org_id, body))


@router.put("/{org_id}/move", summary="调整上级（system:org:update）", response_model=ApiResponse[OrgNode])
async def move_org(org_id: int, body: OrgMove, request: Request, session: DbDep, ctx: UpdateCtx) -> dict[str, Any]:
    return ok(await org_service.move_org(session, ctx, request, org_id, body))


@router.put("/{org_id}/status", summary="启用/停用组织（system:org:update）", response_model=ApiResponse[OrgNode])
async def set_org_status(
    org_id: int, body: OrgStatusBody, request: Request, session: DbDep, ctx: UpdateCtx
) -> dict[str, Any]:
    return ok(await org_service.set_status(session, ctx, request, org_id, body))


@router.delete("/{org_id}", summary="删除组织（system:org:delete）", response_model=ApiResponse[None])
async def delete_org(
    org_id: int,
    request: Request,
    session: DbDep,
    ctx: Annotated[AuthContext, Depends(require_perm("system:org:delete"))],
) -> dict[str, Any]:
    await org_service.delete_org(session, ctx, request, org_id)
    return ok()
