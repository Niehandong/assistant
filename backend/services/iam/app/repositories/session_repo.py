"""会话 sys_user_session 查询与更新（不受数据权限控制）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SysUserSession


async def add(
    session: AsyncSession,
    *,
    sid: uuid.UUID,
    user_id: int,
    refresh_token_hash: str,
    expires_at: datetime,
    now: datetime,
    ip: str | None,
    user_agent: str | None,
) -> SysUserSession:
    row = SysUserSession(
        sid=sid,
        user_id=user_id,
        refresh_token_hash=refresh_token_hash,
        expires_at=expires_at,
        last_active_at=now,
        ip=ip,
        user_agent=user_agent,
        created_by=user_id,
        updated_by=user_id,
    )
    session.add(row)
    await session.flush()
    return row


async def lock_active_by_hash(session: AsyncSession, token_hash: str, now: datetime) -> SysUserSession | None:
    """按刷新令牌哈希取有效会话并加行锁（SELECT ... FOR UPDATE）。"""
    stmt = (
        select(SysUserSession)
        .where(
            SysUserSession.refresh_token_hash == token_hash,
            SysUserSession.revoked_at.is_(None),
            SysUserSession.expires_at > now,
            SysUserSession.is_deleted.is_(False),
        )
        .with_for_update()
    )
    return (await session.scalars(stmt)).first()


async def revoke_by_sid(session: AsyncSession, sid: uuid.UUID, reason: str, now: datetime) -> int:
    result = await session.execute(
        update(SysUserSession)
        .where(SysUserSession.sid == sid, SysUserSession.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason=reason)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def revoke_user_sessions(
    session: AsyncSession, user_id: int, reason: str, now: datetime, except_sid: uuid.UUID | None
) -> list[str]:
    """吊销用户全部未吊销会话（可排除一个），返回被吊销的 sid。"""
    stmt = (
        update(SysUserSession)
        .where(SysUserSession.user_id == user_id, SysUserSession.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason=reason)
        .returning(SysUserSession.sid)
    )
    if except_sid is not None:
        stmt = stmt.where(SysUserSession.sid != except_sid)
    return [str(s) for s in (await session.scalars(stmt)).all()]


async def revoke_users_sessions(
    session: AsyncSession, user_ids: list[int], reason: str, now: datetime
) -> dict[int, list[str]]:
    """批量吊销多个用户的全部未吊销会话（单条 UPDATE），返回 user_id → 被吊销的 sid 列表。"""
    if not user_ids:
        return {}
    stmt = (
        update(SysUserSession)
        .where(SysUserSession.user_id.in_(user_ids), SysUserSession.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason=reason)
        .returning(SysUserSession.user_id, SysUserSession.sid)
    )
    out: dict[int, list[str]] = {}
    for uid, sid in (await session.execute(stmt)).all():
        out.setdefault(int(uid), []).append(str(sid))
    return out
