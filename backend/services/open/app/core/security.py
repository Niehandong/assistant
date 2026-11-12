"""API 密钥的生成、哈希、掩码。明文只在内存中短暂存在，不进日志、不进操作日志。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import string

from app.core.config import Settings, get_settings

KEY_PREFIX = "kb-"
KEY_RANDOM_LENGTH = 40  # base62 随机串长度；明文共 43 位
KEY_PREFIX_LENGTH = 7  # 存储/展示用的前缀长度，如 ``kb-AbCd``
_BASE62 = string.ascii_letters + string.digits


def generate_api_key() -> str:
    """``kb-`` + 40 位 base62（secrets，密码学安全）。"""
    return KEY_PREFIX + "".join(secrets.choice(_BASE62) for _ in range(KEY_RANDOM_LENGTH))


def hash_api_key(plain: str, settings: Settings | None = None) -> str:
    """``HMAC-SHA256(API_KEY_PEPPER, 明文)`` 的 hex（64 位）。"""
    pepper = (settings or get_settings()).API_KEY_PEPPER.encode()
    return hmac.new(pepper, plain.encode(), hashlib.sha256).hexdigest()


def key_prefix_of(plain: str) -> str:
    return plain[:KEY_PREFIX_LENGTH]


def mask_key(prefix: str) -> str:
    """掩码展示：``kb-AbCd****``。"""
    return f"{prefix}****"
