"""认证：登录（含失败锁定）、刷新、登出、当前用户、修改密码（5.1）。"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import LoginFailReason, LoginResult, RevokeReason, Status
from app.core.security import hash_password, sign_access_token, verify_password
from app.models import SysUser
from app.repositories import log_repo, org_repo, user_repo
from app.schemas.auth import MeData, MeUser, TokenData
from app.services import authz_service, session_service
from app.services.session_service import redis_guard
from platform_common.auth import cache_keys
from platform_common.auth.context import AuthContext
from platform_common.db import get_session_factory
from platform_common.errors import BizError, CommonErrors
from platform_common.redis import get_redis

logger = logging.getLogger(__name__)

BAD_CREDENTIALS = (401101, "账号或密码错误")
LOCKED = (401102, "账号已锁定，请 {n} 分钟后再试")
UNAVAILABLE = (401103, "账号不可用，请联系管理员")
REFRESH_INVALID = (401104, "登录已过期，请重新登录")
OLD_PASSWORD_WRONG = (400101, "原密码错误")
NEW_PASSWORD_INVALID = (400102, "新密码不符合规则")
NEW_PASSWORD_SAME = (400103, "新密码不能与当前密码相同")

_FAIL_MESSAGES = {
    LoginFailReason.BAD_CREDENTIALS: "账号或密码错误",
    LoginFailReason.LOCKED: "账号已锁定",
    LoginFailReason.USER_DISABLED: "账号已停用",
    LoginFailReason.ORG_DISABLED: "所属组织已停用",
}


@lru_cache
def _dummy_hash() -> str:
    return hash_password("dummy-password-for-timing")


async def _verify(password: str, password_hash: str) -> bool:
    return await asyncio.to_thread(verify_password, password, password_hash)


async def _record_login(
    *,
    username: str,
    user: SysUser | None,
    fail_reason: LoginFailReason | None,
    ip: str | None,
    user_agent: str | None,
) -> None:
    """同步写登录日志（独立事务）；失败只记运行日志，不影响登录结果。"""
    try:
        async with get_session_factory()() as s:
            await log_repo.add_login_log(
                s,
                username=username,
                user_id=user.id if user else None,
                company_id=user.company_id if user else None,
                dept_id=user.dept_id if user else None,
                result=LoginResult.FAILURE if fail_reason else LoginResult.SUCCESS,
                fail_reason=fail_reason.value if fail_reason else None,
                fail_message=_FAIL_MESSAGES[fail_reason] if fail_reason else None,
                ip=ip,
                user_agent=user_agent,
                login_at=datetime.now(UTC),
            )
            await s.commit()
    except Exception:
        logger.error("写登录日志失败 username=%s", username[:64], exc_info=True)


# 原子"占位"：先检查锁；未锁定则 INCR 失败计数（首次设置窗口 TTL）。计数超过上限即在同一脚本内落锁并清计数。
# 返回 {1, 剩余锁定秒数}（已锁定）或 {0, 本次尝试序号}（放行校验密码，序号 ≤ 上限）。
# 并发 N 路请求时，序号唯一且递增，因此最多 LOGIN_MAX_FAILURES 个请求会真正校验密码。
_RESERVE_ATTEMPT_LUA = """
local ttl = redis.call('TTL', KEYS[1])
if ttl ~= -2 then
  if ttl < 1 then ttl = 1 end
  return {1, ttl}
end
local n = redis.call('INCR', KEYS[2])
if n == 1 then redis.call('EXPIRE', KEYS[2], tonumber(ARGV[2])) end
if n > tonumber(ARGV[1]) then
  redis.call('SET', KEYS[1], '1', 'EX', tonumber(ARGV[3]))
  redis.call('DEL', KEYS[2])
  return {1, tonumber(ARGV[3])}
end
return {0, n}
"""


async def _reserve_attempt(username: str) -> tuple[int | None, int]:
    """原子检查锁并占用一次尝试名额。返回 (锁定剩余秒数 | None, 本次尝试序号)。"""
    s = get_settings()
    async with redis_guard():
        script = get_redis().register_script(_RESERVE_ATTEMPT_LUA)
        locked, value = await script(
            keys=[cache_keys.login_lock(username), cache_keys.login_fail(username)],
            args=[s.LOGIN_MAX_FAILURES, s.LOGIN_FAIL_WINDOW_SECONDS, s.LOGIN_LOCK_SECONDS],
        )
    if int(locked) == 1:
        return max(int(value), 1), 0
    return None, int(value)


async def _register_failure(username: str, attempt: int) -> None:
    """密码错误：第 LOGIN_MAX_FAILURES 次失败立即落锁（序号唯一，只会有一个请求触发）。"""
    s = get_settings()
    if attempt < s.LOGIN_MAX_FAILURES:
        return
    async with redis_guard():
        pipe = get_redis().pipeline()
        pipe.set(cache_keys.login_lock(username), "1", ex=s.LOGIN_LOCK_SECONDS)
        pipe.delete(cache_keys.login_fail(username))
        await pipe.execute()


async def _clear_failures(username: str) -> None:
    async with redis_guard():
        await get_redis().delete(cache_keys.login_fail(username))


async def login(
    session: AsyncSession, username: str, password: str, *, ip: str | None, user_agent: str | None
) -> TokenData:
    """登录。

    连接占用约束（避免并发登录耗尽连接池）：任一时刻本请求最多占用 1 个连接——读取用户后立即
    ``session.close()`` 释放连接，再做 bcrypt 校验与登录日志写入（独立会话）；bcrypt 期间不占连接。
    """
    remaining, attempt = await _reserve_attempt(username)
    user = await user_repo.get_by_username(session, username)
    await session.close()  # 释放连接（user 已加载，close 后仍可读取其属性）
    if remaining is not None:
        await _record_login(
            username=username, user=user, fail_reason=LoginFailReason.LOCKED, ip=ip, user_agent=user_agent
        )
        raise BizError(
            LOCKED[0],
            LOCKED[1].format(n=math.ceil(remaining / 60)),
            data={"remaining_seconds": remaining},
        )

    # 账号不存在时也做一次等价的 bcrypt 比较，避免通过耗时枚举账号
    password_ok = await _verify(password, user.password_hash if user else _dummy_hash())
    if user is None or not password_ok:
        await _register_failure(username, attempt)
        await _record_login(
            username=username, user=user, fail_reason=LoginFailReason.BAD_CREDENTIALS, ip=ip, user_agent=user_agent
        )
        raise BizError(*BAD_CREDENTIALS)
    await _clear_failures(username)

    fail_reason: LoginFailReason | None = None
    if user.status != Status.ENABLED:
        fail_reason = LoginFailReason.USER_DISABLED
    else:
        ctx = await authz_service.get_context(session, user.id)
        if ctx is None or not ctx.org_enabled:
            fail_reason = LoginFailReason.ORG_DISABLED
    if fail_reason is not None:
        await session.close()
        await _record_login(username=username, user=user, fail_reason=fail_reason, ip=ip, user_agent=user_agent)
        raise BizError(*UNAVAILABLE)

    sid, refresh_token = await session_service.create_session(session, user.id, ip=ip, user_agent=user_agent)
    await user_repo.touch_last_login(session, user.id, ip)
    must_change = user.must_change_password
    await session.commit()
    await _record_login(username=username, user=user, fail_reason=None, ip=ip, user_agent=user_agent)
    access_token, expires_in = sign_access_token(user.id, sid)
    return TokenData(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        must_change_password=must_change,
    )


async def refresh(session: AsyncSession, refresh_token: str, *, ip: str | None, user_agent: str | None) -> TokenData:
    row = await session_service.lock_for_refresh(session, refresh_token)
    if row is None:
        raise BizError(*REFRESH_INVALID)
    ctx = await authz_service.get_context(session, row.user_id)
    if ctx is None or not ctx.usable:
        raise BizError(*REFRESH_INVALID)
    sid, user_id, must_change = row.sid, row.user_id, ctx.must_change_password
    new_refresh = await session_service.rotate(session, row, ip=ip, user_agent=user_agent)
    await session.commit()
    access_token, expires_in = sign_access_token(user_id, sid)
    return TokenData(
        access_token=access_token,
        refresh_token=new_refresh,
        expires_in=expires_in,
        must_change_password=must_change,
    )


async def logout(session: AsyncSession, ctx: AuthContext, sid: str) -> None:
    await session_service.revoke_one(session, sid, ctx.user_id, RevokeReason.LOGOUT)
    await session.commit()
    await session_service.purge_one(ctx.user_id, sid)  # 即时生效（提交后钩子为兜底，幂等）


async def get_me(session: AsyncSession, ctx: AuthContext) -> MeData:
    user = await user_repo.get_by_id(session, ctx.user_id)
    if user is None:  # 竞态：用户刚被删除
        raise BizError(*CommonErrors.SESSION_INVALID)
    orgs = await org_repo.get_by_ids(session, {user.org_id, user.company_id})
    permissions, menus = await authz_service.get_me_payload(session, ctx)
    org, company = orgs.get(user.org_id), orgs.get(user.company_id)
    return MeData(
        user=MeUser(
            id=user.id,
            username=user.username,
            name=user.name,
            org_id=user.org_id,
            org_name=org.name if org else None,
            company_id=user.company_id,
            company_name=company.name if company else None,
            mobile=user.mobile,
            email=user.email,
            must_change_password=user.must_change_password,
            is_super_admin=ctx.is_super_admin,
            last_login_at=user.last_login_at,
        ),
        permissions=permissions,
        menus=menus,
    )


def password_rule_errors(password: str) -> list[str]:
    """返回具体不符合的原因（空列表表示合规）。"""
    errors: list[str] = []
    if len(password) < 8 or len(password) > 32:
        errors.append("密码长度须为 8~32 位")
    if not any(c.isascii() and c.isalpha() for c in password):
        errors.append("密码须包含字母")
    if not any(c.isascii() and c.isdigit() for c in password):
        errors.append("密码须包含数字")
    return errors


async def change_password(
    session: AsyncSession, ctx: AuthContext, sid: str, old_password: str, new_password: str
) -> None:
    user = await user_repo.get_by_id(session, ctx.user_id)
    if user is None:
        raise BizError(*CommonErrors.SESSION_INVALID)
    if not await _verify(old_password, user.password_hash):
        raise BizError(*OLD_PASSWORD_WRONG)
    errors = password_rule_errors(new_password)
    if errors:
        raise BizError(
            *NEW_PASSWORD_INVALID,
            data={"errors": [{"field": "new_password", "message": m} for m in errors]},
        )
    if new_password == old_password or await _verify(new_password, user.password_hash):
        raise BizError(*NEW_PASSWORD_SAME)

    new_hash = await asyncio.to_thread(hash_password, new_password)
    await user_repo.update_password(session, user, new_hash)
    sids = await session_service.revoke_all(session, user.id, RevokeReason.PASSWORD_CHANGED, except_sid=sid)
    await session.commit()
    # 先提交再失效缓存，保证其他会话下一次请求即刻被拒绝
    await session_service.purge_cache(user.id, sids, except_sid=sid)
    await authz_service.invalidate_user(user.id)
