"""open.api_key：个人 API 密钥。

受数据权限控制：是（审计按 company_id / dept_id / created_by；本人管理按 created_by，不看数据范围）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, BigInteger, DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import TEXT as PG_TEXT
from sqlalchemy.orm import Mapped, mapped_column

from platform_common.db import AuditMixin, Base, VersionMixin

SCHEMA = "open"


class ApiKey(AuditMixin, VersionMixin, Base):
    __tablename__ = "api_key"
    __table_args__ = (
        Index(
            "uq_api_key_owner_name",
            "created_by",
            "name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_api_key_created_by", "created_by", postgresql_where=text("is_deleted = false")),
        Index("ix_api_key_company_id", "company_id"),
        Index("ix_api_key_dept_id", "dept_id"),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, server_default="all", default="all")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_whitelist: Mapped[list[str]] = mapped_column(
        ARRAY(PG_TEXT), nullable=False, server_default=text("'{}'::text[]"), default=list
    )
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("60"), default=60)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="enabled", default="enabled")
    admin_disabled_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    admin_disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    company_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 创建人创建时的所属公司
    dept_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 创建人创建时的组织节点
