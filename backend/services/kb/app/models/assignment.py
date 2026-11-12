"""知识库分配 kb.dataset_assignment（受数据权限控制：否，随知识库）。"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from platform_common.db import AuditMixin, Base

SCHEMA = "kb"


class DatasetAssignment(AuditMixin, Base):
    __tablename__ = "dataset_assignment"
    __table_args__ = (
        Index("ix_dataset_assignment_dataset_id", "dataset_id"),
        Index(
            "uq_dataset_assignment_target",
            "dataset_id",
            "target_type",
            "target_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "ix_dataset_assignment_target",
            "target_type",
            "target_id",
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": SCHEMA},
    )

    dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    include_children: Mapped[bool] = mapped_column(Boolean, nullable=False)
    permission: Mapped[str] = mapped_column(String(8), nullable=False, server_default="read", default="read")
