"""组织相关 schema（5.2）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from platform_common.response import LocalDatetime

StatusLiteral = Literal["enabled", "disabled"]
ORG_CODE_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"


def _strip_name(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("名称不能为空")
    return v


class OrgNode(BaseModel):
    id: int
    parent_id: int
    name: str
    code: str
    org_type: str
    leader_user_id: int | None
    leader_name: str | None
    sort_order: int
    status: str
    effective_status: str
    company_id: int
    version: int
    manageable: bool = True  # 是否在管理范围内（5.2.0a）；false 时两个 *_blocked_reason 恒为 null
    # 保护规则提示（5.2.0）：仅组织管理树与单节点查询计算；非 null 时前端置灰对应按钮并展示该文案
    disable_blocked_reason: str | None = None
    delete_blocked_reason: str | None = None
    move_blocked_reason: str | None = None
    created_at: LocalDatetime
    children: list[OrgNode] = Field(default_factory=list)


class OrgOption(BaseModel):
    id: int
    parent_id: int
    name: str
    org_type: str
    status: str
    manageable: bool = True
    children: list[OrgOption] = Field(default_factory=list)


class OrgCreate(BaseModel):
    parent_id: int = Field(ge=0)
    org_type: Literal["company", "dept"]
    name: str = Field(min_length=1, max_length=50)
    code: str = Field(pattern=ORG_CODE_PATTERN)
    leader_user_id: int | None = Field(default=None, ge=1)
    sort_order: int = Field(default=0, ge=0, le=9999)
    status: StatusLiteral = "enabled"

    _name = field_validator("name")(_strip_name)


class OrgUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    leader_user_id: int | None = Field(default=None, ge=1)
    sort_order: int = Field(ge=0, le=9999)
    version: int = Field(ge=1)

    _name = field_validator("name")(_strip_name)


class OrgMove(BaseModel):
    parent_id: int = Field(ge=0)
    version: int = Field(ge=1)


class OrgStatusBody(BaseModel):
    status: StatusLiteral
    version: int = Field(ge=1)
