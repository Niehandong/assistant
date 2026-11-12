"""文档管理的请求/响应模型（tech-design-m2 5.5）。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.process_rule import ProcessRule


class UploaderBrief(BaseModel):
    id: int
    name: str


class ProgressInfo(BaseModel):
    done: int
    total: int


class DocumentItem(BaseModel):
    id: int
    name: str
    file_ext: str
    file_size: int
    chunk_mode: Literal["general", "parent_child"]
    char_count: int
    segment_count: int
    child_count: int
    hit_count: int
    uploaded_by: UploaderBrief
    created_at: datetime
    status: Literal["queued", "parsing", "splitting", "indexing", "available", "failed"]
    progress: ProgressInfo | None
    error_code: str | None
    error_message: str | None
    enabled: bool
    version: int


class DocumentDetail(DocumentItem):
    process_rule: dict[str, Any] | None


class DocumentProgressItem(BaseModel):
    id: int
    status: Literal["queued", "parsing", "splitting", "indexing", "available", "failed"]
    progress: ProgressInfo | None
    error_code: str | None
    error_message: str | None
    segment_count: int
    child_count: int
    char_count: int


DocIds = Annotated[list[Annotated[int, Field(ge=1)]], Field(min_length=1, max_length=100)]


def _dedup(ids: list[int]) -> list[int]:
    return list(dict.fromkeys(ids))


class EnabledRequest(BaseModel):
    document_ids: DocIds
    enabled: bool

    @field_validator("document_ids")
    @classmethod
    def _dedup_ids(cls, v: list[int]) -> list[int]:
        return _dedup(v)


class BatchDeleteRequest(BaseModel):
    document_ids: DocIds

    @field_validator("document_ids")
    @classmethod
    def _dedup_ids(cls, v: list[int]) -> list[int]:
        return _dedup(v)


class ReprocessRequest(BaseModel):
    process_rule: ProcessRule
    version: Annotated[int, Field(ge=1)]


class EnabledResult(BaseModel):
    updated: int


class DeleteResult(BaseModel):
    deleted: int
