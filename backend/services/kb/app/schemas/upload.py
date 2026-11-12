"""上传、预览、提交的请求/响应模型（tech-design-m2 5.4）。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from app.core.constants import DocStatus
from app.schemas.process_rule import ProcessRule


class UploadFileResult(BaseModel):
    upload_file_id: int
    name: str
    file_ext: str
    file_size: int
    file_hash: str


class PreviewRequest(BaseModel):
    upload_file_id: Annotated[int, Field(ge=1)]
    process_rule: ProcessRule


class PreviewChildItem(BaseModel):
    position: int
    content: str
    char_count: int
    token_count: int


class PreviewSegmentItem(PreviewChildItem):
    children: list[PreviewChildItem]


class PreviewResult(BaseModel):
    mode: Literal["general", "parent_child"]
    total_segments: int
    total_child_chunks: int
    doc_token_count: int
    segments: list[PreviewSegmentItem]


class SubmitRequest(BaseModel):
    upload_file_ids: Annotated[list[Annotated[int, Field(ge=1)]], Field(min_length=1, max_length=20)]
    process_rule: ProcessRule

    @field_validator("upload_file_ids")
    @classmethod
    def _dedupe(cls, v: list[int]) -> list[int]:
        return list(dict.fromkeys(v))  # 去重并保持顺序


class SubmittedDocument(BaseModel):
    id: int
    name: str
    status: DocStatus


class SubmitResult(BaseModel):
    documents: list[SubmittedDocument]
