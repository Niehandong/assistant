"""我的 API 密钥（tech-design-m3 5.1）。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from platform_common.response import LocalDatetime

ScopeType = Literal["all", "selected"]
StoredStatus = Literal["enabled", "disabled", "admin_disabled"]
KeyStatus = Literal["enabled", "disabled", "admin_disabled", "owner_unavailable", "expired", "no_dataset"]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class ApiKeyBody(BaseModel):
    """创建 / 编辑共用。``dataset_ids`` 个数、``ip_whitelist`` 格式与条数由 service 校验（各自有专属错误码）。"""

    name: Name
    description: Description | None = None
    scope_type: ScopeType = "all"
    dataset_ids: list[int] | None = None
    expires_at: datetime | None = None
    ip_whitelist: list[str] | None = None
    rate_limit_per_min: Annotated[int, Field(ge=1, le=600)] = 60


class ApiKeyUpdateBody(ApiKeyBody):
    version: Annotated[int, Field(ge=1)]


class ApiKeyStatusBody(BaseModel):
    status: Literal["enabled", "disabled"]
    version: Annotated[int, Field(ge=1)]


class VersionBody(BaseModel):
    version: Annotated[int, Field(ge=1)]


class ApiKeyItem(BaseModel):
    id: int
    name: str
    description: str | None
    key_masked: str
    scope_type: ScopeType
    dataset_ids: list[int]
    accessible_dataset_count: int
    status: KeyStatus
    stored_status: StoredStatus
    expires_at: LocalDatetime | None
    ip_whitelist: list[str]
    rate_limit_per_min: int
    calls_7d: int
    failures_7d: int
    last_used_at: LocalDatetime | None
    created_at: LocalDatetime
    version: int


class ApiKeySecretResult(BaseModel):
    """创建 / 重新生成的响应：明文只出现这一次。"""

    api_key: str
    item: ApiKeyItem


class AccessibleDataset(BaseModel):
    id: int
    name: str


class KeyCount(BaseModel):
    count: int
