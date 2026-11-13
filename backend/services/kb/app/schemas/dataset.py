"""知识库接口的请求/响应模型（tech-design-m2 5.2）。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from platform_common.response import LocalDatetime

SearchMethod = Literal["vector", "full_text", "hybrid"]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
MyPermission = Literal["owner", "edit", "read"]


class RetrievalConfig(BaseModel):
    """检索设置（5.2.6）。字段缺省取默认值；多余字段拒绝。"""

    model_config = ConfigDict(extra="forbid")

    search_method: SearchMethod = "vector"
    top_k: int = Field(3, ge=1, le=20)
    score_threshold_enabled: bool = False
    score_threshold: float = Field(0.5, ge=0, le=1)
    reranking_enable: bool = False
    reranking_model_id: int | None = None
    hybrid_mode: Literal["weighted", "rerank"] = "weighted"
    vector_weight: float = Field(0.7, ge=0, le=1)

    @field_validator("score_threshold")
    @classmethod
    def _two_decimals(cls, v: float) -> float:
        if abs(v * 100 - round(v * 100)) > 1e-6:
            raise ValueError("Score 阈值最多两位小数")
        return round(v, 2)

    @field_validator("vector_weight")
    @classmethod
    def _step(cls, v: float) -> float:
        if abs(v * 10 - round(v * 10)) > 1e-6:
            raise ValueError("语义权重步长为 0.1")
        return round(v, 1)

    def needs_rerank_model(self) -> bool:
        """向量/全文且开启 Rerank，或混合检索的 rerank 模式。"""
        if self.search_method == "hybrid":
            return self.hybrid_mode == "rerank"
        return self.reranking_enable

    def normalized(self) -> RetrievalConfig:
        """清理不适用字段：混合检索不使用 reranking_enable；不需要 Rerank 时清空模型。"""
        data = self.model_dump()
        if self.search_method == "hybrid":
            data["reranking_enable"] = False
        else:  # 非混合检索时 hybrid_mode / vector_weight 无意义，保持默认
            data["hybrid_mode"], data["vector_weight"] = "weighted", 0.7
        if not self.needs_rerank_model():
            data["reranking_model_id"] = None
        return RetrievalConfig(**data)


class DatasetCreate(BaseModel):
    name: Name
    description: Annotated[str | None, Field(max_length=400)] = None
    icon: Annotated[str | None, Field(max_length=50)] = None
    embedding_model_id: Annotated[int | None, Field(ge=1)] = None
    retrieval_config: RetrievalConfig | None = None


class DatasetUpdate(BaseModel):
    """基础信息编辑：只更新请求中出现的字段（name 必填）。"""

    name: Name
    description: Annotated[str | None, Field(max_length=400)] = None
    icon: Annotated[str | None, Field(max_length=50)] = None
    embedding_model_id: Annotated[int | None, Field(ge=1)] = None
    version: Annotated[int, Field(ge=1)]


class RetrievalConfigUpdate(BaseModel):
    retrieval_config: RetrievalConfig
    version: Annotated[int, Field(ge=1)]


class DatasetDeleteBody(BaseModel):
    confirm_name: Annotated[str, Field(max_length=200)]


class OwnerBrief(BaseModel):
    id: int
    name: str
    status: Literal["enabled", "disabled", "deleted"]


class ModelBrief(BaseModel):
    id: int
    name: str
    status: Literal["enabled", "disabled"]


class OwnerOrg(BaseModel):
    company_id: int
    company_name: str
    dept_id: int
    dept_name: str


class DatasetItem(BaseModel):
    id: int
    name: str
    description: str | None
    icon: str | None
    owner: OwnerBrief
    my_permission: MyPermission
    chunk_mode: Literal["general", "parent_child"] | None
    indexing_technique: str
    search_method: SearchMethod
    doc_count: int
    processing_count: int
    failed_count: int
    available_doc_count: int
    segment_count: int
    child_segment_count: int
    char_count: int
    embedding_model: ModelBrief
    created_at: LocalDatetime
    updated_at: LocalDatetime


class DatasetDetail(DatasetItem):
    retrieval_config: RetrievalConfig
    last_process_rule: dict[str, object] | None
    owner_org: OwnerOrg
    assignment_count: int
    version: int


class DatasetOption(BaseModel):
    id: int
    name: str
    my_permission: MyPermission
