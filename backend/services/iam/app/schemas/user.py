"""用户相关 schema（5.3）。BE-09 先行提供 UserItem（角色下的用户列表用），BE-08 在此文件追加请求/响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.constants import USERNAME_PATTERN
from platform_common.response import LocalDatetime

StatusLiteral = Literal["enabled", "disabled"]
MOBILE_PATTERN = r"^1\d{10}$"
EMAIL_PATTERN = r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$"


class RoleRef(BaseModel):
    id: int
    name: str


class UserItem(BaseModel):
    """用户对象（5.3）；`roles` 在"角色下的用户"列表中为空数组。"""

    id: int
    username: str
    name: str
    org_id: int
    org_name: str | None
    company_id: int
    company_name: str | None
    roles: list[RoleRef] = Field(default_factory=list)
    mobile: str | None
    email: str | None
    status: str
    is_builtin: bool
    must_change_password: bool
    last_login_at: LocalDatetime | None
    created_at: LocalDatetime
    version: int
    manageable: bool = True  # 是否在操作人管理范围内（5.2.0a：SELF 看到的本人账号为 false）


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


def _strip_name(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("姓名不能为空")
    return v


class UserCreate(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    name: str = Field(min_length=1, max_length=30)
    org_id: int = Field(ge=1)
    mobile: str | None = Field(default=None, pattern=MOBILE_PATTERN)
    email: str | None = Field(default=None, max_length=100, pattern=EMAIL_PATTERN)
    # 密码规则交由 service 校验，以返回 400102（含具体原因）而非通用 400001
    password: str | None = Field(default=None, max_length=128)
    role_ids: list[int] = Field(default_factory=list, max_length=100)
    status: StatusLiteral = "enabled"

    _name = field_validator("name")(_strip_name)
    _password = field_validator("password")(_blank_to_none)


class UserUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    org_id: int = Field(ge=1)
    mobile: str | None = Field(pattern=MOBILE_PATTERN)
    email: str | None = Field(max_length=100, pattern=EMAIL_PATTERN)
    version: int = Field(ge=1)

    _name = field_validator("name")(_strip_name)


class UserStatusBody(BaseModel):
    status: StatusLiteral
    version: int = Field(ge=1)


class ResetPasswordBody(BaseModel):
    password: str | None = Field(default=None, max_length=128)

    _password = field_validator("password")(_blank_to_none)


class AssignRolesBody(BaseModel):
    role_ids: list[int] = Field(max_length=100)
    confirm_self_lockout: bool = False


class UserCreated(BaseModel):
    user: UserItem
    initial_password: str | None


class PasswordReset(BaseModel):
    password: str | None


class UserImpact(BaseModel):
    owned_dataset_count: int | None
    api_key_count: int | None
    degraded: bool
