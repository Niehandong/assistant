"""上传文件 kb.upload_file（受数据权限控制：否，临时数据，过期物理删除）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, BigInteger, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from platform_common.db import AuditMixin, Base

SCHEMA = "kb"


class UploadFile(AuditMixin, Base):
    __tablename__ = "upload_file"
    __table_args__ = (
        Index("ix_upload_file_dataset_id", "dataset_id"),
        Index("ix_upload_file_expires_at", "expires_at"),
        {"schema": SCHEMA},
    )

    dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    file_ext: Mapped[str] = mapped_column(String(10), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    parsed_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    doc_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consumed_document_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
