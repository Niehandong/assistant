"""知识库 kb.dataset（受数据权限控制：是，管理视图/管理员转移；本人列 owner_id）。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import BigInteger, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import DEFAULT_RETRIEVAL_CONFIG
from platform_common.db import AuditMixin, Base, VersionMixin

SCHEMA = "kb"
_DEFAULT_CFG_SQL = "'" + json.dumps(DEFAULT_RETRIEVAL_CONFIG) + "'::jsonb"


def _zero() -> Any:
    return mapped_column(Integer, nullable=False, server_default=text("0"), default=0)


class Dataset(AuditMixin, VersionMixin, Base):
    __tablename__ = "dataset"
    __table_args__ = (
        Index("uq_dataset_owner_name", "owner_id", "name", unique=True, postgresql_where=text("is_deleted = false")),
        Index("ix_dataset_owner_id", "owner_id"),
        Index("ix_dataset_company_id", "company_id"),
        Index("ix_dataset_dept_id", "dept_id"),
        Index("ix_dataset_embedding_model_id", "embedding_model_id"),
        Index("ix_dataset_updated", text("updated_at DESC")),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    company_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dept_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    embedding_model_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    indexing_technique: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="high_quality", default="high_quality"
    )
    retrieval_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text(_DEFAULT_CFG_SQL),
        default=lambda: dict(DEFAULT_RETRIEVAL_CONFIG),
    )
    last_process_rule: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    doc_count: Mapped[int] = _zero()
    processing_count: Mapped[int] = _zero()
    failed_count: Mapped[int] = _zero()
    available_doc_count: Mapped[int] = _zero()
    segment_count: Mapped[int] = _zero()
    child_segment_count: Mapped[int] = _zero()
    char_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"), default=0)
