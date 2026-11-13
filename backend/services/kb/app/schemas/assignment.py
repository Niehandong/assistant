"""分配接口的请求/响应模型（tech-design-m2 5.3）。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from platform_common.response import LocalDatetime

TargetTypeLit = Literal["user", "dept", "company"]
PermissionLit = Literal["read", "edit"]


class AssignmentCreate(BaseModel):
    target_type: TargetTypeLit
    target_id: Annotated[int, Field(ge=1)]
    include_children: bool | None = None  # user 忽略；dept 默认 true；company 默认 false
    permission: PermissionLit = "read"


class AssignmentUpdate(BaseModel):
    permission: PermissionLit
    include_children: bool


class UserBrief(BaseModel):
    id: int
    name: str


class AssignmentItem(BaseModel):
    id: int
    target_type: TargetTypeLit
    target_id: int
    target_name: str
    target_path: str | None
    target_valid: bool
    include_children: bool
    permission: PermissionLit
    created_by: UserBrief
    created_at: LocalDatetime


class AssignableOrgNode(BaseModel):
    id: int
    parent_id: int
    name: str
    org_type: Literal["group", "company", "dept"]
    status: Literal["enabled", "disabled"]
    children: list[AssignableOrgNode] = []


class AssignableUser(BaseModel):
    id: int
    username: str
    name: str
    org_name: str | None
    company_name: str | None
