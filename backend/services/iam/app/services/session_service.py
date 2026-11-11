"""会话管理：PG（sys_user_session）+ Redis（auth:sess / auth:user_sess）。

对其他 service 的入口：

* ``await revoke_all(session, user_id, reason, except_sid=None) -> list[str]``：在调用方事务内吊销该用户全部
  会话（PG），并注册"提交成功后清理 Redis"；返回被吊销的 sid。需要**即时生效**时，调用方 ``commit`` 之后再
  ``await purge_cache(user_id, sids, except_sid)``（幂等）。
* ``await purge_cache(user_id, sids=(), except_sid=None)``：删除 Redis 会话键。
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator, Collection
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import generate_refresh_token
from app.models import SysUserSession
from app.repositories import session_repo
from app.services import authz_service
from platform_common.auth import cache_keys
from platform_common.crypto import sha256_hex
from platform_common.errors import BizError, CommonErrors
from platform_common.redis import get_redis

logger = logging.getLogger(__name__)


@asynccontextmanager
async def redis_guard() -> AsyncIterator[None]:
    """Redis 不可用 → 503001（不泄露细节）。"""
    try:
        yield
    except (RedisError, OSError) as exc:
        logger.error("Redis 操作失败", exc_info=True)
        raise BizError(*CommonErrors.DEPENDENCY_UNAVAILABLE) from exc


def _ttl_seconds() -> int:
    return get_settings().REFRESH_TOKEN_EXPIRE_DAYS * 86400


async def create_session(
    session: AsyncSession, user_id: int, *, ip: str | None, user_agent: str | None
) -> tuple[uuid.UUID, str]:
    """新建会话：写 PG（未提交）与 Redis，返回 (sid, refresh_token 明文)。"""
    now = datetime.now(UTC)
    sid = uuid.uuid4()
    refresh_token = generate_refresh_token()
    await session_repo.add(
        session,
        sid=sid,
        user_id=user_id,
        refresh_token_hash=sha256_hex(refresh_token),
        expires_at=now + timedelta(seconds=_ttl_seconds()),
        now=now,
        ip=ip,
        user_agent=user_agent[:500] if user_agent else None,
    )
    ttl = _ttl_seconds()
    async with redis_guard():
        r = get_redis()
        pipe = r.pipeline()
        pipe.set(cache_keys.session(str(sid)), json.dumps({"user_id": user_id, "created_at": now.isoformat()}), ex=ttl)
        pipe.sadd(cache_keys.user_sessions(user_id), str(sid))
        pipe.expire(cache_keys.user_sessions(user_id), ttl)
        await pipe.execute()
    return sid, refresh_token


async def lock_for_refresh(session: AsyncSession, refresh_token: str) -> SysUserSession | None:
    """按刷新令牌取有效会话并加行锁；同时要求 Redis 会话存在。"""
    row = await session_repo.lock_active_by_hash(session, sha256_hex(refresh_token), datetime.now(UTC))
    if row is None:
        return None
    async with redis_guard():
        if not await get_redis().exists(cache_keys.session(str(row.sid))):
            return None
    return row


async def rotate(session: AsyncSession, row: SysUserSession, *, ip: str | None, user_agent: str | None) -> str:
    """轮换刷新令牌并续期 PG / Redis（Redis 续期在提交前，失败则整体回滚）。"""
    now = datetime.now(UTC)
    refresh_token = generate_refresh_token()
    ttl = _ttl_seconds()
    row.refresh_token_hash = sha256_hex(refresh_token)
    row.expires_at = now + timedelta(seconds=ttl)
    row.last_active_at = now
    row.ip = ip
    row.user_agent = user_agent[:500] if user_agent else None
    row.updated_by = row.user_id
    await session.flush()
    async with redis_guard():
        r = get_redis()
        pipe = r.pipeline()
        pipe.expire(cache_keys.session(str(row.sid)), ttl)
        pipe.expire(cache_keys.user_sessions(row.user_id), ttl)
        await pipe.execute()
    return refresh_token


async def purge_cache(user_id: int, sids: Collection[str] = (), except_sid: str | None = None) -> None:
    """删除 Redis 会话：参数 sids 与 ``auth:user_sess`` 集合中的全部 sid（排除 except_sid）。幂等。"""
    async with redis_guard():
        r = get_redis()
        members = await r.smembers(cache_keys.user_sessions(user_id))
        targets = ({str(m) for m in members} | set(sids)) - ({except_sid} if except_sid else set())
        if not targets:
            return
        pipe = r.pipeline()
        pipe.delete(*[cache_keys.session(s) for s in targets])
        pipe.srem(cache_keys.user_sessions(user_id), *targets)
        await pipe.execute()


async def _purge_quietly(user_id: int, sids: list[str], except_sid: str | None) -> None:
    try:
        await purge_cache(user_id, sids, except_sid)
    except BizError:
        logger.error("提交后清理会话缓存失败 user_id=%s", user_id)


async def revoke_all(
    session: AsyncSession, user_id: int, reason: str, except_sid: str | uuid.UUID | None = None
) -> list[str]:
    """吊销用户全部会话（可排除 except_sid）。PG 在调用方事务内更新，不提交。"""
    except_uuid = uuid.UUID(str(except_sid)) if except_sid else None
    sids = await session_repo.revoke_user_sessions(session, user_id, reason, datetime.now(UTC), except_uuid)
    authz_service.run_after_commit(session, _purge_quietly, user_id, sids, str(except_uuid) if except_uuid else None)
    return sids


async def revoke_many(session: AsyncSession, user_ids: list[int], reason: str) -> dict[int, list[str]]:
    """批量吊销多个用户的全部会话（PG 在调用方事务内更新，不提交）。

    返回 user_id → 被吊销 sid；同时注册"提交成功后清理 Redis"。要求即时生效时，调用方 commit 之后
    对每个 user_id 再 ``await purge_cache(uid, sids)``（幂等）。无会话的用户不出现在结果中，但调用方仍应
    对全部 user_ids 清理 Redis 集合（purge_cache 以集合为准）。
    """
    revoked = await session_repo.revoke_users_sessions(session, user_ids, reason, datetime.now(UTC))
    for uid in user_ids:
        authz_service.run_after_commit(session, _purge_quietly, uid, revoked.get(uid, []), None)
    return revoked


async def revoke_one(session: AsyncSession, sid: str | uuid.UUID, user_id: int, reason: str) -> None:
    """吊销单个会话：PG（未提交）+ 注册提交后清理 Redis。"""
    sid_uuid = uuid.UUID(str(sid))
    await session_repo.revoke_by_sid(session, sid_uuid, reason, datetime.now(UTC))
    authz_service.run_after_commit(session, _purge_one, user_id, str(sid_uuid))


async def _purge_one(user_id: int, sid: str) -> None:
    try:
        async with redis_guard():
            r = get_redis()
            pipe = r.pipeline()
            pipe.delete(cache_keys.session(sid))
            pipe.srem(cache_keys.user_sessions(user_id), sid)
            await pipe.execute()
    except BizError:
        logger.error("提交后清理会话缓存失败 sid=%s", sid)


purge_one = _purge_one
