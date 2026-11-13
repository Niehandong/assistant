"""open.api_call_log：开放检索调用日志（受数据权限控制：是；created_by = 密钥创建人，无法识别密钥时为 0）。

保留 180 天，由清理任务物理删除（不走逻辑删除）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, desc, text
from sqlalchemy.orm import Mapped, mapped_column

from platform_common.db import AuditMixin, Base

SCHEMA = "open"


class ApiCallLog(AuditMixin, Base):
    __tablename__ = "api_call_log"
    __table_args__ = (
        Index("ix_call_log_key_called", "api_key_id", desc("called_at")),
        Index("ix_call_log_owner_called", "created_by", desc("called_at")),
        Index("ix_call_log_company_called", "company_id", desc("called_at")),
        Index("ix_call_log_dept_id", "dept_id"),
        Index("ix_call_log_called_at", "called_at"),
        {"schema": SCHEMA},
    )

    request_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    api_key_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    key_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    key_prefix: Mapped[str | None] = mapped_column(String(16), nullable=True)
    company_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dept_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dataset_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dataset_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
