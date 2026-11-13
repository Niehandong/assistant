"""管理视图与所有权转移的请求/响应模型（tech-design-m2 5.2.8、5.8）。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.assignment import AssignmentItem
from app.schemas.dataset import ModelBrief, RetrievalConfig
from platform_common.response import LocalDatetime

OwnerStatus = Literal["enabled", "disabled", "deleted"]


class AdminOwner(BaseModel):
    id: int
    name: str
    username: str
    status: OwnerStatus


class OrgBrief(BaseModel):
    id: int
    name: str


class AdminDatasetItem(BaseModel):
    id: int
    name: str
    owner: AdminOwner
    company: OrgBrief
    dept: OrgBrief
    chunk_mode: Literal["general", "parent_child"] | None
    doc_count: int
    segment_count: int
    child_segment_count: int
    assignment_count: int
    created_at: LocalDatetime
    updated_at: LocalDatetime
    version: int


class AdminDatasetDetail(AdminDatasetItem):
    description: str | None
    embedding_model: ModelBrief
    retrieval_config: RetrievalConfig
    assignments: list[AssignmentItem]


class TransferBody(BaseModel):
    """所有者自行转移 / 管理员单个转移。"""

    receiver_user_id: Annotated[int, Field(ge=1)]
    version: Annotated[int, Field(ge=1)]


class BatchTransferBody(BaseModel):
    from_user_id: Annotated[int, Field(ge=1)]
    receiver_user_id: Annotated[int, Field(ge=1)]
    dataset_ids: Annotated[
        list[Annotated[int, Field(ge=1)]] | None, Field(min_length=1, max_length=500, description="缺省 = 范围内全部")
    ] = None


class BatchTransferResult(BaseModel):
    transferred: int


class AdminOwnerOption(BaseModel):
    id: int
    username: str
    name: str
    status: OwnerStatus
    dataset_count: int
