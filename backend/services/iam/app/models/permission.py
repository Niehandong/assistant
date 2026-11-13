"""权限点 sys_permission（受数据权限控制：否），由 seed 注册表维护。"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Index, Integer, String, false, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.org import SCHEMA
from platform_common.db import AuditMixin, Base


class SysPermission(AuditMixin, Base):
    __tablename__ = "sys_permission"
    __table_args__ = (Index("ix_sys_permission_parent_id", "parent_id"), {"schema": SCHEMA})

    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    perm_type: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_id: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"), default=0)
    path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    service: Mapped[str] = mapped_column(String(16), nullable=False)
    super_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false(), default=False)
