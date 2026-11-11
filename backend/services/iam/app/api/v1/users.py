"""用户接口（5.3.1 ~ 5.3.9）。路由层只收参、声明权限、调 service。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.user import (
    AssignRolesBody,
    PasswordReset,
    ResetPasswordBody,
    UserCreate,
    UserCreated,
    UserImpact,
    UserItem,
    UserStatusBody,
    UserUpdate,
)
from app.services import user_service
from platform_common.auth.context import AuthContext
from platform_common.auth.deps import require_perm
from platform_common.db import get_db
from platform_common.pagination import PageParamsDep
from platform_common.response import ApiResponse, Page, ok, page

router = APIRouter(prefix="/system/users", tags=["users"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
ListCtx = Annotated[AuthContext, Depends(require_perm("system:user:list"))]


@router.get("", summary="用户列表（system:user:list）", response_model=ApiResponse[Page[UserItem]])
async def list_users(
    ctx: ListCtx,
    session: DbDep,
    pp: PageParamsDep,
    org_id: Annotated[int | None, Query(ge=1, description="组织节点，含下级")] = None,
    username: Annotated[str | None, Query(max_length=32)] = None,
    name: Annotated[str | None, Query(max_length=30)] = None,
    mobile: Annotated[str | None, Query(max_length=11)] = None,
    status: Annotated[str | None, Query(pattern="^(enabled|disabled)$")] = None,
) -> dict[str, Any]:
    items, total = await user_service.list_users(
        session, ctx, pp, org_id=org_id, username=username, name=name, mobile=mobile, status=status
    )
    return page(items, total, pp.page, pp.page_size)


@router.get("/{user_id}", summary="用户详情（system:user:list）", response_model=ApiResponse[UserItem])
async def get_user(user_id: int, ctx: ListCtx, session: DbDep) -> dict[str, Any]:
    return ok(await user_service.get_user(session, ctx, user_id))


@router.post("", summary="新增用户（system:user:create）", response_model=ApiResponse[UserCreated])
async def create_user(
    body: UserCreate,
    request: Request,
    session: DbDep,
    ctx: Annotated[AuthContext, Depends(require_perm("system:user:create"))],
) -> dict[str, Any]:
    return ok(await user_service.create_user(session, ctx, request, body))


@router.put("/{user_id}", summary="编辑用户（system:user:update）", response_model=ApiResponse[UserItem])
async def update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    session: DbDep,
    ctx: Annotated[AuthContext, Depends(require_perm("system:user:update"))],
) -> dict[str, Any]:
    return ok(await user_service.update_user(session, ctx, request, user_id, body))


@router.put("/{user_id}/status", summary="启用/停用用户（system:user:status）", response_model=ApiResponse[UserItem])
async def set_user_status(
    user_id: int,
    body: UserStatusBody,
    request: Request,
    session: DbDep,
    ctx: Annotated[AuthContext, Depends(require_perm("system:user:status"))],
) -> dict[str, Any]:
    return ok(await user_service.set_status(session, ctx, request, user_id, body))


@router.post(
    "/{user_id}/reset-password",
    summary="重置密码（system:user:reset_pwd）",
    response_model=ApiResponse[PasswordReset],
)
async def reset_user_password(
    user_id: int,
    request: Request,
    session: DbDep,
    ctx: Annotated[AuthContext, Depends(require_perm("system:user:reset_pwd"))],
    body: ResetPasswordBody | None = None,
) -> dict[str, Any]:
    return ok(await user_service.reset_password(session, ctx, request, user_id, body or ResetPasswordBody()))


@router.put("/{user_id}/roles", summary="分配角色（system:user:assign）", response_model=ApiResponse[UserItem])
async def assign_user_roles(
    user_id: int,
    body: AssignRolesBody,
    request: Request,
    session: DbDep,
    ctx: Annotated[AuthContext, Depends(require_perm("system:user:assign"))],
) -> dict[str, Any]:
    return ok(await user_service.assign_roles(session, ctx, request, user_id, body))


@router.delete("/{user_id}", summary="删除用户（system:user:delete）", response_model=ApiResponse[None])
async def delete_user(
    user_id: int,
    request: Request,
    session: DbDep,
    ctx: Annotated[AuthContext, Depends(require_perm("system:user:delete"))],
) -> dict[str, Any]:
    await user_service.delete_user(session, ctx, request, user_id)
    return ok()


@router.get(
    "/{user_id}/impact", summary="停用/删除前的影响提示（system:user:list）", response_model=ApiResponse[UserImpact]
)
async def user_impact(user_id: int, ctx: ListCtx, session: DbDep) -> dict[str, Any]:
    return ok(await user_service.impact(session, ctx, user_id))
