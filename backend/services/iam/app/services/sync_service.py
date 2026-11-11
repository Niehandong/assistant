"""内部增量同步（5.6.3、5.6.4）：游标 (updated_at, id)。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import org_repo, user_repo
from app.schemas.sync import OrgRef, OrgSyncPage, SyncNext, UserRef, UserSyncPage


async def sync_users(session: AsyncSession, updated_after: datetime | None, after_id: int, limit: int) -> UserSyncPage:
    rows = await user_repo.sync_page(session, updated_after, after_id, limit)
    page_rows = rows[:limit]
    nxt = SyncNext(updated_after=page_rows[-1].updated_at, after_id=page_rows[-1].id) if len(rows) > limit else None
    return UserSyncPage(items=[UserRef.model_validate(r) for r in page_rows], next=nxt)


async def sync_orgs(session: AsyncSession, updated_after: datetime | None, after_id: int, limit: int) -> OrgSyncPage:
    rows = await org_repo.sync_page(session, updated_after, after_id, limit)
    page_rows = rows[:limit]
    nxt = SyncNext(updated_after=page_rows[-1].updated_at, after_id=page_rows[-1].id) if len(rows) > limit else None
    return OrgSyncPage(items=[OrgRef.model_validate(r) for r in page_rows], next=nxt)
