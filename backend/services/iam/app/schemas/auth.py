"""认证接口 schema（5.1）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.permission import MenuNode
from platform_common.response import LocalDatetime


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=64)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    # 新密码规则（8~32、字母+数字，含空串）由 service 校验并返回 400102（中文具体原因）/400103，这里只防超长
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(max_length=128)


class TokenData(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    must_change_password: bool


class MeUser(BaseModel):
    id: int
    username: str
    name: str
    org_id: int
    org_name: str | None
    company_id: int
    company_name: str | None
    mobile: str | None
    email: str | None
    must_change_password: bool
    is_super_admin: bool
    last_login_at: LocalDatetime | None


class MeData(BaseModel):
    user: MeUser
    permissions: list[str]
    menus: list[MenuNode]
