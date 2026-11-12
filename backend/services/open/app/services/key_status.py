"""密钥状态计算（tech-design-m3 3.2）。纯函数，不访问 IO。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from platform_common.auth.context import AuthContext

APIKEY_MANAGE_PERM = "openapi:apikey:manage"

StoredStatus = Literal["enabled", "disabled", "admin_disabled"]
KeyStatus = Literal["enabled", "disabled", "admin_disabled", "owner_unavailable", "expired", "no_dataset"]


def owner_available(owner_ctx: AuthContext | None) -> bool:
    """创建人可用：上下文存在、账号可用、且仍拥有 ``openapi:apikey:manage``（super_admin 恒有）。"""
    return owner_ctx is not None and owner_ctx.usable and owner_ctx.has_perm(APIKEY_MANAGE_PERM)


def compute(
    stored_status: str,
    expires_at: datetime | None,
    owner_ctx: AuthContext | None,
    accessible_count: int,
    *,
    now: datetime | None = None,
) -> KeyStatus:
    """优先级：admin_disabled > disabled > owner_unavailable > expired > no_dataset > enabled。"""
    if stored_status == "admin_disabled":
        return "admin_disabled"
    if stored_status == "disabled":
        return "disabled"
    if not owner_available(owner_ctx):
        return "owner_unavailable"
    if expires_at is not None and expires_at <= (now or datetime.now(UTC)):
        return "expired"
    if accessible_count <= 0:
        return "no_dataset"
    return "enabled"
