"""会话 sys_user_session（受数据权限控制：否）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CHAR, BigInteger, DateTime, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.org import SCHEMA
from platform_common.db import AuditMixin, Base


class SysUserSession(AuditMixin, Base):
    __tablename__ = "sys_user_session"
    __table_args__ = (Index("ix_sys_user_session_user_id", "user_id"), {"schema": SCHEMA})

    sid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
