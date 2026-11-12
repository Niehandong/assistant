"""调用日志（tech-design-m3 5.2、5.3）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from platform_common.response import LocalDatetime

CallResult = Literal[
    "success",
    "key_invalid",
    "key_disabled",
    "key_expired",
    "ip_not_allowed",
    "dataset_not_found",
    "invalid_params",
    "rate_limited",
    "model_unavailable",
    "service_unavailable",
    "internal_error",
]


class LogKeyRef(BaseModel):
    id: int
    name: str
    key_masked: str


class LogDatasetRef(BaseModel):
    id: int
    name: str | None


class CallLogItem(BaseModel):
    id: int
    called_at: LocalDatetime
    request_id: str
    api_key: LogKeyRef | None
    dataset: LogDatasetRef | None
    query: str | None
    result_count: int
    latency_ms: int
    result: CallResult
    error_code: int | None
    client_ip: str | None


class LogCreatorRef(BaseModel):
    id: int
    name: str


class AuditCallLogItem(CallLogItem):
    creator: LogCreatorRef | None
