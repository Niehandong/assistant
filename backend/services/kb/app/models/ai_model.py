"""模型配置 kb.ai_model（受数据权限控制：否，全局资源）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, false, text
from sqlalchemy.orm import Mapped, mapped_column

from platform_common.db import AuditMixin, Base, VersionMixin

SCHEMA = "kb"


class AiModel(AuditMixin, VersionMixin, Base):
    __tablename__ = "ai_model"
    __table_args__ = (
        Index("uq_ai_model_name", "name", unique=True, postgresql_where=text("is_deleted = false")),
        Index(
            "uq_ai_model_default",
            "model_type",
            unique=True,
            postgresql_where=text("is_default AND is_deleted = false"),
        ),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    model_type: Mapped[str] = mapped_column(String(16), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_hint: Mapped[str | None] = mapped_column(String(16), nullable=True)
    dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("512"), default=512)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="disabled", default="disabled")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false(), default=False)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
