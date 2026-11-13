"""iam 只读副本 kb.user_ref / kb.org_ref（受数据权限控制：否）。主键 = iam 中的 ID，不自增。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, false, func, text
from sqlalchemy.orm import Mapped, mapped_column

from platform_common.db import Base

SCHEMA = "kb"


class _RefTimeMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    created_by: Mapped[int] = mapped_column(BigInteger, server_default=text("0"), default=0, nullable=False)
    updated_by: Mapped[int] = mapped_column(BigInteger, server_default=text("0"), default=0, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(server_default=false(), default=False, nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserRef(_RefTimeMixin, Base):
    __tablename__ = "user_ref"
    __table_args__ = (
        Index("ix_user_ref_org_id", "org_id"),
        Index("ix_user_ref_company_id", "company_id"),
        Index("ix_user_ref_name", "name"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    company_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


class OrgRef(_RefTimeMixin, Base):
    __tablename__ = "org_ref"
    __table_args__ = (
        Index("ix_org_ref_parent_id", "parent_id"),
        Index("ix_org_ref_company_id", "company_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    parent_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ancestors: Mapped[str] = mapped_column(String(1000), nullable=False)
    org_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    company_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
