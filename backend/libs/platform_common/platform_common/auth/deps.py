"""鉴权依赖：get_auth_context（总体方案 3.5.1 的 1~6 步）、require_login、require_perm。"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import Request

from platform_common.auth import cache_keys, runtime
from platform_common.auth.context import AuthContext, fetch_context_from_iam, parse_context
from platform_common.auth.jwt import verify_access_token
from platform_common.errors import BizError, CommonErrors
from platform_common.redis import get_redis

logger = logging.getLogger(__name__)


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise BizError(*CommonErrors.UNAUTHENTICATED)
    return token.strip()


def _session_belongs_to(raw_session: str | bytes, user_id: int) -> bool:
    """会话 JSON 中的 user_id 必须与令牌 sub 一致（纵深防御：防止 sub 与他人 sid 拼接）。"""
    try:
        data = json.loads(raw_session)
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("user_id") == user_id


async def _authenticate(request: Request) -> AuthContext:
    cached: AuthContext | None = getattr(request.state, "ctx", None)
    if cached is not None:
        return cached
    settings = runtime.get_settings()
    claims = verify_access_token(_bearer_token(request), settings)  # 1. 验签/exp → 401001
    try:  # 2. 一次 MGET
        raw_sess, raw_ctx, raw_epoch = await get_redis().mget(
            [cache_keys.session(claims.sid), cache_keys.authz_context(claims.user_id), cache_keys.AUTHZ_EPOCH]
        )
    except Exception as exc:
        logger.error("Redis 不可用", exc_info=True)
        raise BizError(*CommonErrors.DEPENDENCY_UNAVAILABLE) from exc
    if raw_sess is None or not _session_belongs_to(raw_sess, claims.user_id):  # 3. 会话已失效 / 不属于该用户
        raise BizError(*CommonErrors.SESSION_INVALID)
    ctx = parse_context(raw_ctx)
    if ctx is None or ctx.epoch != int(raw_epoch or 0):  # 4. 回源 iam
        ctx = await fetch_context_from_iam(claims.user_id)
        if ctx is None:
            raise BizError(*CommonErrors.SESSION_INVALID)
    if ctx.user_id != claims.user_id or not ctx.usable:  # 5. 停用/删除/组织停用
        raise BizError(*CommonErrors.SESSION_INVALID)
    request.state.ctx = ctx
    return ctx


async def _login(request: Request, allow_must_change: bool) -> AuthContext:
    ctx = await _authenticate(request)
    if ctx.must_change_password and not allow_must_change:  # 6. 强制改密
        raise BizError(*CommonErrors.MUST_CHANGE_PASSWORD)
    return ctx


async def get_auth_context(request: Request) -> AuthContext:
    """完整校验链，结果放 request.state.ctx；must_change_password 时拒绝（403002）。"""
    return await _login(request, False)


def require_login(allow_must_change: bool = False) -> Callable[..., Awaitable[AuthContext]]:
    """仅要求已登录。``allow_must_change=True`` 用于改密/个人信息等白名单接口。"""

    async def dep(request: Request) -> AuthContext:
        return await _login(request, allow_must_change)

    return dep


def require_perm(*codes: str, mode: Literal["all", "any"] = "all") -> Callable[..., Awaitable[AuthContext]]:
    """要求权限码。用法：``dependencies=[Depends(require_perm("system:user:create"))]``。"""
    if not codes:
        raise ValueError("require_perm 至少需要一个权限码")

    async def dep(request: Request) -> AuthContext:
        ctx = await _login(request, False)
        checks = [ctx.has_perm(c) for c in codes]
        if not (all(checks) if mode == "all" else any(checks)):
            raise BizError(*CommonErrors.FORBIDDEN)
        return ctx

    return dep
