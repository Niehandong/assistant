"""日志表：sys_login_log、sys_operation_log（受数据权限控制：是；只增不改，保留期物理清理）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.org import SCHEMA
from platform_common.db import AuditMixin, Base


class SysLoginLog(AuditMixin, Base):
    """本人列 created_by = user_id（账号不存在时为 0）。"""

    __tablename__ = "sys_login_log"
    __table_args__ = (
        Index("ix_sys_login_log_username", "username"),
        Index("ix_sys_login_log_company_id", "company_id"),
        Index("ix_sys_login_log_dept_id", "dept_id"),
        Index("ix_sys_login_log_login_at", "login_at"),
        {"schema": SCHEMA},
    )

    username: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    company_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dept_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    fail_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fail_message: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SysOperationLog(AuditMixin, Base):
    """本人列 created_by = operator_id。"""

    __tablename__ = "sys_operation_log"
    __table_args__ = (
        Index("ix_sys_operation_log_operator_id", "operator_id"),
        Index("ix_sys_operation_log_company_id", "company_id"),
        Index("ix_sys_operation_log_dept_id", "dept_id"),
        Index("ix_sys_operation_log_occurred_at", "occurred_at"),
        {"schema": SCHEMA},
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    service: Mapped[str] = mapped_column(String(16), nullable=False)
    operator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    operator_username: Mapped[str] = mapped_column(String(32), nullable=False)
    operator_name: Mapped[str] = mapped_column(String(30), nullable=False)
    company_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dept_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
