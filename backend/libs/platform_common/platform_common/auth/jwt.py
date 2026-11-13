"""access token 验签（仅公钥，只验不签；签发在 iam）。"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import jwt
from pydantic import BaseModel

from platform_common.auth import runtime
from platform_common.config import BaseServiceSettings
from platform_common.errors import BizError, CommonErrors

logger = logging.getLogger(__name__)


class AccessClaims(BaseModel):
    user_id: int
    sid: str
    exp: datetime
    iat: datetime | None = None


@lru_cache(maxsize=4)
def _load_public_key(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def verify_access_token(token: str, settings: BaseServiceSettings | None = None) -> AccessClaims:
    """验签名、exp、iss，要求含 sub(user_id)、sid；任何失败 → BizError(401001)。"""
    s = settings or runtime.get_settings()
    try:
        key = _load_public_key(str(s.jwt_public_key_path))
    except OSError as exc:
        logger.error("JWT 公钥不可读: %s", s.jwt_public_key_path)
        raise BizError(*CommonErrors.INTERNAL) from exc
    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=s.JWT_ISSUER,
            options={"require": ["exp", "sub", "sid"]},
        )
        return AccessClaims(
            user_id=int(payload["sub"]),
            sid=str(payload["sid"]),
            exp=datetime.fromtimestamp(payload["exp"]).astimezone(),
            iat=datetime.fromtimestamp(payload["iat"]).astimezone() if "iat" in payload else None,
        )
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise BizError(*CommonErrors.UNAUTHENTICATED) from exc
