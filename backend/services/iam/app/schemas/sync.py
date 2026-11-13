"""内部同步与事件载荷：UserRef / OrgRef（5.6.3、5.6.4、5.7）。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from platform_common.response import LocalDatetime


class UserRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    name: str
    status: str
    is_deleted: bool
    org_id: int
    company_id: int
    updated_at: LocalDatetime


class OrgRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: int
    ancestors: str
    org_type: str
    name: str
    code: str
    status: str
    is_deleted: bool
    company_id: int
    sort_order: int
    updated_at: LocalDatetime


class SyncNext(BaseModel):
    updated_after: LocalDatetime
    after_id: int


class UserSyncPage(BaseModel):
    items: list[UserRef]
    next: SyncNext | None


class OrgSyncPage(BaseModel):
    items: list[OrgRef]
    next: SyncNext | None
