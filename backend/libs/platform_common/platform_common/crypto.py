"""哈希、HMAC、随机串工具。"""

from __future__ import annotations

import hashlib
import hmac
import secrets


def _b(value: str | bytes) -> bytes:
    return value.encode("utf-8") if isinstance(value, str) else value


def sha256_hex(value: str | bytes) -> str:
    return hashlib.sha256(_b(value)).hexdigest()


def hmac_sha256_hex(key: str | bytes, message: str | bytes) -> str:
    return hmac.new(_b(key), _b(message), hashlib.sha256).hexdigest()


def random_token(nbytes: int = 32) -> str:
    """URL 安全的随机串（长度约 nbytes*4/3）。"""
    return secrets.token_urlsafe(nbytes)


def constant_time_equal(a: str | bytes, b: str | bytes) -> bool:
    return hmac.compare_digest(_b(a), _b(b))
