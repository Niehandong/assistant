"""内部接口凭据校验（X-Internal-Token）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Header

from platform_common.auth import runtime
from platform_common.crypto import constant_time_equal
from platform_common.errors import BizError, CommonErrors


async def require_internal(x_internal_token: Annotated[str | None, Header()] = None) -> None:
    """缺失或不匹配 → BizError(401901)。"""
    expected = runtime.get_settings().INTERNAL_API_TOKEN
    if not x_internal_token or not constant_time_equal(x_internal_token, expected):
        raise BizError(*CommonErrors.INTERNAL_TOKEN_INVALID)
