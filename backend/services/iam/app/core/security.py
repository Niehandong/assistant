"""安全工具：签发 access token（RS256）、bcrypt 密码哈希、随机密码、密码规则。"""

from __future__ import annotations

import re
import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import bcrypt
import jwt

from app.core.config import Settings, get_settings
from app.core.constants import PASSWORD_PATTERN
from platform_common.crypto import random_token

BCRYPT_COST = 12
REFRESH_TOKEN_PREFIX = "rt_"
_PASSWORD_RE = re.compile(PASSWORD_PATTERN)


@lru_cache(maxsize=2)
def _load_private_key(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def sign_access_token(user_id: int, sid: str | uuid.UUID, settings: Settings | None = None) -> tuple[str, int]:
    """签发 access token，返回 (token, expires_in 秒)。

    claims：iss、sub=str(user_id)、sid、iat、exp、typ=access；RS256。
    """
    s = settings or get_settings()
    now = datetime.now(UTC)
    expires_in = s.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    payload = {
        "iss": s.JWT_ISSUER,
        "sub": str(user_id),
        "sid": str(sid),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "typ": "access",
    }
    token = jwt.encode(payload, _load_private_key(str(s.jwt_private_key_path)), algorithm="RS256")
    return token, expires_in


def generate_refresh_token() -> str:
    """``rt_`` + 48 字节 urlsafe 随机串；库中只存 SHA-256。"""
    return REFRESH_TOKEN_PREFIX + random_token(48)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_COST)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:  # 超过 72 字节或哈希格式非法
        return False


def validate_password_rule(password: str) -> bool:
    """8~32 位，同时含字母和数字。"""
    return bool(_PASSWORD_RE.match(password))


def generate_password(length: int = 12) -> str:
    """生成满足密码规则的随机密码（至少各 1 位大写、小写、数字）。"""
    length = min(max(length, 8), 32)
    alphabet = string.ascii_letters + string.digits
    chars = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
    ]
    chars += [secrets.choice(alphabet) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)
