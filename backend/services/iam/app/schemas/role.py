"""角色相关 schema（5.4）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from platform_common.response import LocalDatetime

DataScopeLiteral = Literal["ALL", "COMPANY_AND_CHILD", "COMPANY", "DEPT_AND_CHILD", "DEPT", "SELF", "CUSTOM"]
StatusLiteral = Literal["enabled", "disabled"]
ROLE_CODE_PATTERN = r"^[A-Za-z0-9_]{2,50}$"


def _dedup(values: list[int]) -> list[int]:
    return list(dict.fromkeys(values))


class RoleItem(BaseModel):
    id: int
    code: str
    name: str
    role_type: str
    owner_company_id: int | None
    owner_company_name: str | None
    data_scope: str
    status: str
    remark: str | None
    is_builtin: bool
    builtin_key: str | None
    user_count: int
    editable: bool
    created_at: LocalDatetime
    version: int


class RoleDetail(RoleItem):
    permission_ids: list[int]
    custom_org_ids: list[int]


class RoleCreate(BaseModel):
    code: str = Field(pattern=ROLE_CODE_PATTERN)
    name: str = Field(min_length=1, max_length=30)
    role_type: Literal["group", "company"]
    owner_company_id: int | None = Field(default=None, ge=1)
    data_scope: DataScopeLiteral = "SELF"
    custom_org_ids: list[int] = Field(default_factory=list, max_length=500)
    status: StatusLiteral = "enabled"
    remark: str | None = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("名称不能为空")
        return v

    @field_validator("custom_org_ids")
    @classmethod
    def _dedup_orgs(cls, v: list[int]) -> list[int]:
        return _dedup(v)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=30)
    status: StatusLiteral | None = None
    remark: str | None = Field(default=None, max_length=200)
    version: int = Field(ge=1)
    confirm_self_lockout: bool = False

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("名称不能为空")
        return v


class RoleGrant(BaseModel):
    permission_ids: list[int] = Field(max_length=1000)
    data_scope: DataScopeLiteral
    custom_org_ids: list[int] = Field(default_factory=list, max_length=500)
    version: int = Field(ge=1)
    confirm_self_lockout: bool = False

    @field_validator("permission_ids", "custom_org_ids")
    @classmethod
    def _dedup_ids(cls, v: list[int]) -> list[int]:
        return _dedup(v)


class AssignableRole(BaseModel):
    id: int
    name: str
    code: str
    role_type: str
    data_scope: str
    assigned: bool
