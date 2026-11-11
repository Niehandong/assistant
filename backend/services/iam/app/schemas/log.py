"""日志接口 schema（5.5）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from platform_common.response import LocalDatetime


class OperationLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: LocalDatetime
    operator_id: int
    operator_username: str
    operator_name: str
    company_name: str | None
    module: str
    action: str
    target_type: str
    target_id: str | None
    target_name: str | None
    result: str
    error_message: str | None
    ip: str | None
    service: str


class OperationLogDetail(OperationLogItem):
    summary: dict[str, Any]
    user_agent: str | None
    request_id: str | None


class LoginLogItem(BaseModel):
    id: int
    login_at: LocalDatetime
    username: str
    user_id: int | None
    user_name: str | None
    company_name: str | None
    result: str
    fail_reason: str | None
    fail_message: str | None
    ip: str | None
    user_agent: str | None
