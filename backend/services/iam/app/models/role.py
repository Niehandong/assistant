"""角色相关：sys_role（受数据权限控制：否）、sys_role_org、sys_role_permission、sys_user_role（关联表，物理删除）。"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Index, String, UniqueConstraint, false, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.org import SCHEMA
from platform_common.db import AuditMixin, Base, VersionMixin


class SysRole(AuditMixin, VersionMixin, Base):
    __tablename__ = "sys_role"
    __table_args__ = (
        Index("ix_sys_role_owner_company_id", "owner_company_id"),
        {"schema": SCHEMA},
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    role_type: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_company_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    data_scope: Mapped[str] = mapped_column(String(32), nullable=False, server_default="SELF", default="SELF")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="enabled", default="enabled")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false(), default=False)
    builtin_key: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)


Index(
    "uq_sys_role_name",
    func.coalesce(SysRole.owner_company_id, 0),
    SysRole.name,
    unique=True,
    postgresql_where=text("is_deleted = false"),
)


class SysRoleOrg(AuditMixin, Base):
    __tablename__ = "sys_role_org"
    __table_args__ = (
        UniqueConstraint("role_id", "org_id", name="uq_sys_role_org"),
        Index("ix_sys_role_org_org_id", "org_id"),
        {"schema": SCHEMA},
    )

    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


class SysRolePermission(AuditMixin, Base):
    __tablename__ = "sys_role_permission"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_sys_role_permission"),
        Index("ix_sys_role_permission_permission_id", "permission_id"),
        {"schema": SCHEMA},
    )

    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    permission_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


class SysUserRole(AuditMixin, Base):
    __tablename__ = "sys_user_role"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_sys_user_role"),
        Index("ix_sys_user_role_user_id", "user_id"),
        Index("ix_sys_user_role_role_id", "role_id"),
        {"schema": SCHEMA},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
