"""角色接口（5.4.1 ~ 5.4.8）。路由层只收参、声明权限、调 service。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.role import AssignableRole, RoleCreate, RoleDetail, RoleGrant, RoleItem, RoleUpdate
from app.schemas.user import UserItem
from app.services import role_service
from platform_common.auth.context import AuthContext
from platform_common.auth.deps import require_perm
from platform_common.db import get_db
from platform_common.pagination import PageParamsDep
from platform_common.response import ApiResponse, Page, ok, page

router = APIRouter(prefix="/system/roles", tags=["roles"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
ListCtx = Annotated[AuthContext, Depends(require_perm("system:role:list"))]
AssignCtx = Annotated[AuthContext, Depends(require_perm("system:user:assign", "system:user:create", mode="any"))]


@router.get("", summary="角色列表（system:role:list）", response_model=ApiResponse[Page[RoleItem]])
async def list_roles(
    ctx: ListCtx,
    session: DbDep,
    pp: PageParamsDep,
    name: Annotated[str | None, Query(max_length=30)] = None,
    code: Annotated[str | None, Query(max_length=50)] = None,
    role_type: Annotated[str | None, Query(pattern="^(group|company)$")] = None,
    status: Annotated[str | None, Query(pattern="^(enabled|disabled)$")] = None,
    owner_company_id: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    items, total = await role_service.list_roles(
        session,
        ctx,
        pp,
        name=name,
        code=code,
        role_type=role_type,
        status=status,
        owner_company_id=owner_company_id,
    )
    return page(items, total, pp.page, pp.page_size)


@router.get(
    "/assignable",
    summary="可分配角色（system:user:assign 或 system:user:create）",
    response_model=ApiResponse[list[AssignableRole]],
)
async def assignable_roles(
    ctx: AssignCtx,
    session: DbDep,
    user_id: Annotated[int | None, Query(ge=1, description="已有用户；与 org_id 二选一")] = None,
    org_id: Annotated[int | None, Query(ge=1, description="新建用户的目标组织；与 user_id 二选一")] = None,
) -> dict[str, Any]:
    return ok(await role_service.list_assignable(session, ctx, user_id=user_id, org_id=org_id))


@router.get("/{role_id}", summary="角色详情（system:role:list）", response_model=ApiResponse[RoleDetail])
async def get_role(role_id: int, ctx: ListCtx, session: DbDep) -> dict[str, Any]:
    return ok(await role_service.get_role_detail(session, ctx, role_id))


@router.post("", summary="新增角色（system:role:create）", response_model=ApiResponse[RoleDetail])
async def create_role(
    body: RoleCreate,
    request: Request,
    session: DbDep,
    ctx: Annotated[AuthContext, Depends(require_perm("system:role:create"))],
) -> dict[str, Any]:
    return ok(await role_service.create_role(session, ctx, request, body))


@router.put("/{role_id}", summary="编辑角色（system:role:update）", response_model=ApiResponse[RoleDetail])
async def update_role(
    role_id: int,
    body: RoleUpdate,
    request: Request,
    session: DbDep,
    ctx: Annotated[AuthContext, Depends(require_perm("system:role:update"))],
) -> dict[str, Any]:
    return ok(await role_service.update_role(session, ctx, request, role_id, body))


@router.put(
    "/{role_id}/grants",
    summary="分配权限与数据范围（system:role:grant）",
    response_model=ApiResponse[RoleDetail],
)
async def grant_role(
    role_id: int,
    body: RoleGrant,
    request: Request,
    session: DbDep,
    ctx: Annotated[AuthContext, Depends(require_perm("system:role:grant"))],
) -> dict[str, Any]:
    return ok(await role_service.grant_role(session, ctx, request, role_id, body))


@router.delete("/{role_id}", summary="删除角色（system:role:delete）", response_model=ApiResponse[None])
async def delete_role(
    role_id: int,
    request: Request,
    session: DbDep,
    ctx: Annotated[AuthContext, Depends(require_perm("system:role:delete"))],
) -> dict[str, Any]:
    await role_service.delete_role(session, ctx, request, role_id)
    return ok()


@router.get("/{role_id}/users", summary="角色下的用户（system:role:list）", response_model=ApiResponse[Page[UserItem]])
async def list_role_users(role_id: int, ctx: ListCtx, session: DbDep, pp: PageParamsDep) -> dict[str, Any]:
    items, total = await role_service.list_role_users(session, ctx, role_id, pp)
    return page(items, total, pp.page, pp.page_size)
