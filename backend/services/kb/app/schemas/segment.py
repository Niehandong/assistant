"""分段管理的请求/响应模型（tech-design-m2 5.6）。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

IndexStatus = Literal["pending", "indexed", "updating", "failed"]


class ChildChunkItem(BaseModel):
    id: int
    position: int
    content: str
    char_count: int
    token_count: int
    edited: bool
    index_status: IndexStatus
    index_error: str | None
    version: int


class SegmentItem(BaseModel):
    id: int
    position: int
    segment_type: Literal["general", "parent"]
    content: str
    keywords: list[str]
    char_count: int
    token_count: int
    enabled: bool
    edited: bool
    hit_count: int
    index_status: IndexStatus
    index_error: str | None
    version: int
    children: list[ChildChunkItem]


# 内容/关键词的业务校验（400511/400512）在 service 中完成，这里只做类型约束
class SegmentCreate(BaseModel):
    content: str
    keywords: list[str] = Field(default_factory=list)


class SegmentUpdate(BaseModel):
    content: str
    keywords: list[str] | None = None
    version: Annotated[int, Field(ge=1)]
    confirm_regenerate_children: bool = False


class SegmentEnabledBody(BaseModel):
    enabled: bool


class ChildCreate(BaseModel):
    content: str


class ChildUpdate(BaseModel):
    content: str
    version: Annotated[int, Field(ge=1)]
