"""iam 事件发布（stream:iam.events）：user.upserted / org.upserted，事务提交后发布。

调用约定：在同一事务内完成变更后调用（无需先 flush/refresh）；提交成功才真正发布，回滚丢弃。
payload 为 UserRef / OrgRef（JSON 模式，时间带 +08:00）。
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.base import object_state

from app.models import SysOrg, SysUser
from app.schemas.sync import OrgRef, UserRef
from platform_common.events.publisher import publish_after_commit
from platform_common.events.streams import STREAM_IAM_EVENTS

USER_UPSERTED = "user.upserted"
ORG_UPSERTED = "org.upserted"


async def publish_user_upserted(session: AsyncSession, user: SysUser) -> None:
    # flush 后 updated_at 由数据库生成/刷新，需 refresh 才能在异步会话中安全读取
    await session.flush()
    await session.refresh(user, attribute_names=["updated_at"])
    payload = UserRef.model_validate(user).model_dump(mode="json")
    publish_after_commit(session, STREAM_IAM_EVENTS, USER_UPSERTED, payload)


async def _ensure_updated_at(session: AsyncSession, obj: SysUser | SysOrg) -> None:
    """仅当 updated_at 尚未加载（刚被 ORM 更新/插入）时才 refresh，批量场景避免逐行查询。"""
    if "updated_at" in object_state(obj).unloaded:
        await session.refresh(obj, attribute_names=["updated_at"])


async def publish_users_upserted(session: AsyncSession, users: Iterable[SysUser]) -> None:
    await session.flush()
    for u in users:
        await _ensure_updated_at(session, u)
        payload = UserRef.model_validate(u).model_dump(mode="json")
        publish_after_commit(session, STREAM_IAM_EVENTS, USER_UPSERTED, payload)


async def publish_org_upserted(session: AsyncSession, org: SysOrg) -> None:
    await session.flush()
    await session.refresh(org, attribute_names=["updated_at"])
    payload = OrgRef.model_validate(org).model_dump(mode="json")
    publish_after_commit(session, STREAM_IAM_EVENTS, ORG_UPSERTED, payload)


async def publish_orgs_upserted(session: AsyncSession, orgs: Iterable[SysOrg]) -> None:
    """组织移动时子树每个节点各一条。"""
    await session.flush()
    for o in orgs:
        await _ensure_updated_at(session, o)
        payload = OrgRef.model_validate(o).model_dump(mode="json")
        publish_after_commit(session, STREAM_IAM_EVENTS, ORG_UPSERTED, payload)
