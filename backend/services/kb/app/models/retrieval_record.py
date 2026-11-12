"""召回测试记录 kb.retrieval_record（受数据权限控制：否；仅本人可见）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from platform_common.db import AuditMixin, Base

SCHEMA = "kb"


class RetrievalRecord(AuditMixin, Base):
    __tablename__ = "retrieval_record"
    __table_args__ = (
        Index("ix_retrieval_record_user", "dataset_id", "created_by", text("created_at DESC")),
        {"schema": SCHEMA},
    )

    dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    retrieval_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
