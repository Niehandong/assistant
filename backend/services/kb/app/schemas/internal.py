"""内部接口的请求/响应模型（tech-design-m2 5.9）。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.dataset import SearchMethod
from app.schemas.retrieval import RetrievalResult


class RetrieveOverrides(BaseModel):
    """未传项用知识库默认；传入 ``score_threshold`` 即视为开启阈值。"""

    search_method: SearchMethod | None = None
    top_k: Annotated[int | None, Field(ge=1, le=20)] = None
    score_threshold: Annotated[float | None, Field(ge=0, le=1)] = None
    reranking_enable: bool | None = None


class InternalRetrieveBody(BaseModel):
    user_id: Annotated[int, Field(ge=1)]
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    overrides: RetrieveOverrides | None = None
    source: Literal["open_api", "chat"]


class DatasetRef(BaseModel):
    id: int
    name: str


class InternalRetrievalResult(RetrievalResult):
    dataset: DatasetRef


class AccessibleBody(BaseModel):
    user_ids: Annotated[list[Annotated[int, Field(ge=1)]], Field(min_length=1, max_length=100)]
    dataset_ids: Annotated[list[Annotated[int, Field(ge=1)]] | None, Field(max_length=500)] = None


class AccessibleResult(BaseModel):
    items: dict[str, list[int]]


class BriefBody(BaseModel):
    ids: Annotated[list[Annotated[int, Field(ge=1)]], Field(min_length=1, max_length=500)]


class DatasetBrief(BaseModel):
    id: int
    name: str
    is_deleted: bool


class CountResult(BaseModel):
    count: int
