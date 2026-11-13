"""父子分段的子块 kb.child_chunk（受数据权限控制：否，随知识库）。"""

from __future__ import annotations

from typing import Any

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import BigInteger, Boolean, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from platform_common.db import AuditMixin, Base, VersionMixin

SCHEMA = "kb"


class ChildChunk(AuditMixin, VersionMixin, Base):
    __tablename__ = "child_chunk"
    __table_args__ = (
        Index("ix_child_chunk_segment_gen_pos", "segment_id", "generation", "position"),
        Index("ix_child_chunk_document_id", "document_id"),
        Index("ix_child_search", "dataset_id", postgresql_where=text("search_enabled")),
        Index("ix_child_chunk_tsv", "tsv", postgresql_using="gin", postgresql_where=text("search_enabled")),
        {"schema": SCHEMA},
    )

    dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    segment_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"), default=1)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    pending_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    edited: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    index_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending", default="pending")
    index_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    embedding: Mapped[Any | None] = mapped_column(HALFVEC(), nullable=True)
    tsv: Mapped[Any | None] = mapped_column(TSVECTOR, nullable=True)
    # 冗余：写入向量时同时写入（= 知识库当时的 Embedding 模型），HNSW 部分索引的谓词（3.10.1）；无向量为 NULL
    embedding_model_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    search_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
