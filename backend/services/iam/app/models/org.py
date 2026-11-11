"""组织树 sys_org（受数据权限控制：是；本人列 created_by）。"""

from __future__ import annotations

from sqlalchemy import BigInteger, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from platform_common.db import AuditMixin, Base, VersionMixin

SCHEMA = "iam"


class SysOrg(AuditMixin, VersionMixin, Base):
    __tablename__ = "sys_org"
    __table_args__ = (
        Index("ix_sys_org_parent_id", "parent_id"),
        Index("ix_sys_org_company_id", "company_id"),
        Index("ix_sys_org_dept_id", "dept_id"),
        Index("ix_sys_org_parent_sort", "parent_id", "sort_order", "created_at"),
        Index("uq_sys_org_parent_name", "parent_id", "name", unique=True, postgresql_where=text("is_deleted = false")),
        Index(
            "uq_sys_org_group",
            "org_type",
            unique=True,
            postgresql_where=text("org_type = 'group' AND is_deleted = false"),
        ),
        {"schema": SCHEMA},
    )

    parent_id: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"), default=0)
    ancestors: Mapped[str] = mapped_column(String(1000), nullable=False, server_default="0", default="0")
    org_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    leader_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="enabled", default="enabled")
    company_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dept_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


__all__ = ["SCHEMA", "SysOrg"]
