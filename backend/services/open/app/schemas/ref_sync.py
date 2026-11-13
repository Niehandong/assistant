"""iam 只读副本同步载荷：UserRef / OrgRef（tech-design-m1 5.6.3、5.6.4、5.7）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class UserRefPayload(BaseModel):
    id: int
    username: str
    name: str
    status: str
    is_deleted: bool
    org_id: int
    company_id: int
    updated_at: datetime


class OrgRefPayload(BaseModel):
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
    updated_at: datetime
