"""用户 sys_user（受数据权限控制：是；本人列 created_by）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String, false, text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.models.org import SCHEMA
from platform_common.db import AuditMixin, Base, VersionMixin


class SysUser(AuditMixin, VersionMixin, Base):
    __tablename__ = "sys_user"
    __table_args__ = (
        Index("ix_sys_user_org_id", "org_id"),
        Index("ix_sys_user_company_id", "company_id"),
        Index("ix_sys_user_dept_id", "dept_id"),
        Index(
            "uq_sys_user_mobile",
            "mobile",
            unique=True,
            postgresql_where=text("mobile IS NOT NULL AND is_deleted = false"),
        ),
        {"schema": SCHEMA},
    )

    username: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    company_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dept_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mobile: Mapped[str | None] = mapped_column(String(11), nullable=True)
    email: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="enabled", default="enabled")
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false(), default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true(), default=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
