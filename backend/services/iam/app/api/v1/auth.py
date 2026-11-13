"""认证接口（5.1）：login / refresh 为 public，其余为 login（允许改密前调用）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.schemas.auth import ChangePasswordRequest, LoginRequest, MeData, RefreshRequest, TokenData
from app.services import auth_service
from platform_common.auth.context import AuthContext
from platform_common.auth.deps import require_login
from platform_common.auth.jwt import verify_access_token
from platform_common.client_ip import get_client_ip
from platform_common.db import get_db
from platform_common.errors import BizError, CommonErrors
from platform_common.response import ApiResponse, ok

router = APIRouter(prefix="/auth", tags=["auth"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
LoginCtx = Annotated[AuthContext, Depends(require_login(allow_must_change=True))]


def _client(request: Request) -> tuple[str | None, str | None]:
    return get_client_ip(request, get_settings().TRUSTED_PROXIES), request.headers.get("user-agent")


def _current_sid(request: Request) -> str:
    """当前请求 access token 中的 sid（require_login 已校验过会话有效）。"""
    header = request.headers.get("authorization", "")
    _, _, token = header.partition(" ")
    if not token.strip():
        raise BizError(*CommonErrors.UNAUTHENTICATED)
    return verify_access_token(token.strip()).sid


@router.post("/login", summary="登录（public）", response_model=ApiResponse[TokenData])
async def login(body: LoginRequest, request: Request, session: DbDep) -> dict[str, Any]:
    ip, ua = _client(request)
    return ok(await auth_service.login(session, body.username, body.password, ip=ip, user_agent=ua))


@router.post("/refresh", summary="刷新令牌（public，凭刷新令牌）", response_model=ApiResponse[TokenData])
async def refresh(body: RefreshRequest, request: Request, session: DbDep) -> dict[str, Any]:
    ip, ua = _client(request)
    return ok(await auth_service.refresh(session, body.refresh_token, ip=ip, user_agent=ua))


@router.post("/logout", summary="登出（login）", response_model=ApiResponse[None])
async def logout(request: Request, ctx: LoginCtx, session: DbDep) -> dict[str, Any]:
    await auth_service.logout(session, ctx, _current_sid(request))
    return ok()


@router.get("/me", summary="当前用户、权限码、菜单（login）", response_model=ApiResponse[MeData])
async def me(ctx: LoginCtx, session: DbDep) -> dict[str, Any]:
    return ok(await auth_service.get_me(session, ctx))


@router.put("/password", summary="修改本人密码（login）", response_model=ApiResponse[None])
async def change_password(
    body: ChangePasswordRequest, request: Request, ctx: LoginCtx, session: DbDep
) -> dict[str, Any]:
    await auth_service.change_password(session, ctx, _current_sid(request), body.old_password, body.new_password)
    return ok()
