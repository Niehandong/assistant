"""open.api_key_dataset：密钥"指定知识库"范围（受数据权限控制：否；纯关联表，允许物理删除）。"""

from __future__ import annotations

from sqlalchemy import BigInteger, Index
from sqlalchemy.orm import Mapped, mapped_column

from platform_common.db import AuditMixin, Base

SCHEMA = "open"


class ApiKeyDataset(AuditMixin, Base):
    __tablename__ = "api_key_dataset"
    __table_args__ = (
        Index("uq_api_key_dataset", "api_key_id", "dataset_id", unique=True),
        {"schema": SCHEMA},
    )

    api_key_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
