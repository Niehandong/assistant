"""模型配置接口的请求/响应模型（tech-design-m2 5.1）。"""

from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from platform_common.response import LocalDatetime

ModelTypeLit = Literal["embedding", "rerank"]
StatusLit = Literal["enabled", "disabled"]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
ModelName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
BaseUrl = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


def _check_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("服务地址必须是 http/https 地址")
    return value.rstrip("/")


class _UrlMixin(BaseModel):
    @field_validator("base_url", check_fields=False)
    @classmethod
    def _url(cls, v: str) -> str:
        return _check_url(v)


class ModelCreate(_UrlMixin):
    name: Name
    model_type: ModelTypeLit
    base_url: BaseUrl
    model_name: ModelName
    api_key: Annotated[str | None, Field(max_length=500)] = None
    dimension: Annotated[int | None, Field(ge=1, le=16000)] = None
    max_input_tokens: Annotated[int, Field(ge=1, le=131072)] = 512
    status: StatusLit = "disabled"
    is_default: bool = False


class ModelUpdate(_UrlMixin):
    name: Name
    base_url: BaseUrl
    model_name: ModelName
    api_key: Annotated[str | None, Field(max_length=500)] = None  # None 不修改；"" 清空
    dimension: Annotated[int | None, Field(ge=1, le=16000)] = None
    max_input_tokens: Annotated[int, Field(ge=1, le=131072)] = 512
    status: StatusLit | None = None
    is_default: bool | None = None
    version: Annotated[int, Field(ge=1)]


class ModelStatusBody(BaseModel):
    status: StatusLit
    version: Annotated[int, Field(ge=1)]


class ModelDefaultBody(BaseModel):
    version: Annotated[int, Field(ge=1)]


class ModelTestBody(_UrlMixin):
    model_id: Annotated[int | None, Field(ge=1)] = None
    model_type: ModelTypeLit
    base_url: Annotated[str | None, Field(max_length=500)] = None
    model_name: Annotated[str | None, Field(max_length=100)] = None
    api_key: Annotated[str | None, Field(max_length=500)] = None

    @field_validator("base_url")
    @classmethod
    def _url_optional(cls, v: str | None) -> str | None:
        return None if v is None or not v.strip() else _check_url(v.strip())


class ModelTestResult(BaseModel):
    success: bool
    dimension: int | None = None
    latency_ms: int | None = None
    error_message: str | None = None


class ModelItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    model_type: str
    base_url: str
    model_name: str
    api_key_hint: str | None
    dimension: int | None
    max_input_tokens: int
    status: str
    is_default: bool
    dataset_count: int = 0
    last_test_at: LocalDatetime | None
    last_test_ok: bool | None
    version: int
    created_at: LocalDatetime
    updated_at: LocalDatetime


class ModelOption(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    model_type: str
    dimension: int | None
    max_input_tokens: int
    is_default: bool
