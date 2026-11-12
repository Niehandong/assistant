"""API 密钥审计（tech-design-m3 5.3）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.schemas.api_key import KeyStatus, ScopeType, StoredStatus
from app.schemas.call_log import AuditCallLogItem, LogCreatorRef
from platform_common.response import LocalDatetime

AuditStatus = Literal["enabled", "disabled", "admin_disabled", "expired", "owner_unavailable"]


class AuditCreator(BaseModel):
    id: int
    name: str
    username: str
    status: str


class AuditOrgRef(BaseModel):
    id: int
    name: str


class AuditApiKeyItem(BaseModel):
    """``ApiKeyItem`` 去掉 ``dataset_ids`` / ``ip_whitelist``，增加创建人、公司、部门。"""

    id: int
    name: str
    description: str | None
    key_masked: str
    scope_type: ScopeType
    accessible_dataset_count: int
    status: KeyStatus
    stored_status: StoredStatus
    expires_at: LocalDatetime | None
    rate_limit_per_min: int
    calls_7d: int
    failures_7d: int
    last_used_at: LocalDatetime | None
    created_at: LocalDatetime
    version: int
    creator: AuditCreator
    company: AuditOrgRef
    dept: AuditOrgRef


class AuditCapabilities(BaseModel):
    can_view_unknown_calls: bool


__all__ = ["AuditApiKeyItem", "AuditCallLogItem", "AuditCapabilities", "AuditCreator", "AuditOrgRef", "LogCreatorRef"]
