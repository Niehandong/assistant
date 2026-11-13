"""密钥记录缓存（tech-design-m3 3.3）：Redis ``open:key:{hash}``。

读取与回填由开放检索鉴权链（BE-27）负责；任何改变密钥可用性的写操作（编辑、启停、管理员停用、
重新生成、删除）都必须在提交后调用 ``invalidate`` 同步删除对应哈希的缓存。
"""

from __future__ import annotations

import logging

from platform_common.redis import get_redis

logger = logging.getLogger(__name__)

NULL_MARKER = "null"  # 哈希不存在时的负缓存值（TTL 60s）
NULL_TTL_SECONDS = 60


def cache_key(key_hash: str) -> str:
    return f"open:key:{key_hash}"


def last_used_key(key_id: int) -> str:
    return f"open:lastused:{key_id}"


async def invalidate(*key_hashes: str) -> None:
    """删除缓存；Redis 故障只记日志（缓存有 TTL 兜底，且鉴权链本身 fail-closed）。"""
    keys = [cache_key(h) for h in key_hashes if h]
    if not keys:
        return
    try:
        await get_redis().delete(*keys)
    except Exception:
        logger.error("密钥缓存删除失败", exc_info=True)
