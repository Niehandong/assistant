"""文档 kb.document（受数据权限控制：否，随知识库）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, BigInteger, Boolean, DateTime, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from platform_common.db import AuditMixin, Base, VersionMixin

SCHEMA = "kb"


class Document(AuditMixin, VersionMixin, Base):
    __tablename__ = "document"
    __table_args__ = (
        Index("uq_document_upload_file_id", "upload_file_id", unique=True),
        Index(
            "uq_document_dataset_hash",
            "dataset_id",
            "file_hash",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_document_dataset_status", "dataset_id", "status"),
        Index("ix_document_dataset_created", "dataset_id", text("created_at DESC")),
        {"schema": SCHEMA},
    )

    dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    upload_file_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    file_ext: Mapped[str] = mapped_column(String(10), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    parsed_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    chunk_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    process_rule: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued", default="queued")
    failed_stage: Mapped[str | None] = mapped_column(String(8), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    progress_done: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    progress_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    process_attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"), default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    child_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    hit_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"), default=0)
