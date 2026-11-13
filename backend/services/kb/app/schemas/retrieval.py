"""召回测试 / 检索结果的请求与响应模型（tech-design-m2 5.7；与内部检索接口 5.9.1、开放 API 的 records 结构一致）。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from app.schemas.dataset import RetrievalConfig
from platform_common.response import LocalDatetime


class RetrieveTestBody(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    retrieval_config: RetrievalConfig | None = None


class RecallRetrievalConfig(RetrievalConfig):
    """生效的检索设置 + Rerank 模型名称（模型已被删除时为 null）。"""

    reranking_model_name: str | None = None


class RecallChildChunk(BaseModel):
    id: int
    position: int
    content: str
    score: float


class RecallDocument(BaseModel):
    id: int
    name: str


class RecallRecord(BaseModel):
    segment_id: int
    position: int
    segment_type: Literal["general", "parent"]
    content: str
    score: float
    keywords: list[str]
    document: RecallDocument
    child_chunks: list[RecallChildChunk]


class RetrievalResult(BaseModel):
    query: str
    retrieval_config: RecallRetrievalConfig
    rerank_skipped: bool
    rerank_skipped_reason: str | None
    records: list[RecallRecord]


class RetrieveRecordItem(BaseModel):
    id: int
    query: str
    search_method: Literal["vector", "full_text", "hybrid"]
    retrieval_config: RetrievalConfig
    result_count: int
    created_at: LocalDatetime
