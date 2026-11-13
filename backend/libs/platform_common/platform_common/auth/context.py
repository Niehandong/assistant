"""权限上下文（AuthContext）与数据范围模型。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ValidationError, computed_field

from platform_common.auth import cache_keys, runtime
from platform_common.errors import BizError, CommonErrors
from platform_common.redis import get_redis

logger = logging.getLogger(__name__)


class DataScope(BaseModel):
    all: bool = False
    company_ids: list[int] = []
    org_ids: list[int] = []
    include_self: bool = False


class AuthContext(BaseModel):
    user_id: int
    username: str
    name: str
    status: Literal["enabled", "disabled"]
    is_deleted: bool
    org_enabled: bool
    org_id: int
    company_id: int
    org_path: list[int]
    is_super_admin: bool
    must_change_password: bool
    permissions: list[str]
    data_scope: DataScope
    epoch: int
    computed_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def usable(self) -> bool:
        """账号可用：启用、未删除、所属组织链启用。"""
        return self.status == "enabled" and not self.is_deleted and self.org_enabled

    def has_perm(self, code: str) -> bool:
        """super_admin 恒为 True。"""
        return self.is_super_admin or code in self.permissions


def parse_context(raw: str | bytes | None) -> AuthContext | None:
    """解析缓存中的 JSON；缺失或损坏返回 None（调用方回源）。"""
    if not raw:
        return None
    try:
        return AuthContext.model_validate(json.loads(raw))
    except (ValueError, ValidationError):
        logger.warning("authz 缓存内容损坏，回源重算")
        return None


async def fetch_context_from_iam(user_id: int) -> AuthContext | None:
    """缓存未命中时回源：已注册 loader（iam 本地）优先，否则调 iam 内部接口（iam 同时回写缓存）。
    用户不存在 → None；iam 不可用 → BizError(503001)。"""
    loader = runtime.get_context_loader()
    if loader is not None:
        return await loader(user_id)
    return await _fetch_via_http(user_id)


async def _fetch_via_http(user_id: int) -> AuthContext | None:
    try:
        data = await runtime.get_iam_client().get(f"/internal/v1/authz/contexts/{user_id}")
    except BizError as exc:
        if exc.code == CommonErrors.NOT_FOUND[0]:
            return None
        raise
    try:
        return AuthContext.model_validate(data)
    except ValidationError as exc:
        logger.error("iam 返回的 AuthContext 结构不合法")
        raise BizError(*CommonErrors.DEPENDENCY_UNAVAILABLE) from exc


async def load_auth_context(user_id: int) -> AuthContext | None:
    """MGET authz:ctx:{uid} + authz:epoch；命中且 epoch 一致直接返回，否则回源 iam。"""
    try:
        raw_ctx, raw_epoch = await get_redis().mget([cache_keys.authz_context(user_id), cache_keys.AUTHZ_EPOCH])
    except Exception as exc:
        logger.error("Redis 不可用", exc_info=True)
        raise BizError(*CommonErrors.DEPENDENCY_UNAVAILABLE) from exc
    ctx = parse_context(raw_ctx)
    if ctx is not None and ctx.epoch == int(raw_epoch or 0):
        return ctx
    return await fetch_context_from_iam(user_id)
