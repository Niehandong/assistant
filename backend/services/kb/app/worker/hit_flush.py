"""召回次数落库：Redis 哈希 kb:hits:segment / kb:hits:document → segment.hit_count / document.hit_count。

流程：持有 Redis 锁 → 先处理上次崩溃遗留的临时 key → ``RENAME`` 当前 key 到临时 key（此后新计数写入新 key，
不丢）→ 事务内累加并提交 → 删除临时 key。提交与删除之间崩溃最多导致一批计数重复累加（可接受）。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Mapping
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from platform_common.db import get_session_factory
from platform_common.redis import get_redis

logger = logging.getLogger("kb.worker.hits")

KINDS = {
    "segment": "UPDATE kb.segment t SET hit_count = t.hit_count + v.n "
    "FROM unnest(CAST(:ids AS bigint[]), CAST(:ns AS bigint[])) AS v(id, n) WHERE t.id = v.id",
    "document": "UPDATE kb.document t SET hit_count = t.hit_count + v.n "
    "FROM unnest(CAST(:ids AS bigint[]), CAST(:ns AS bigint[])) AS v(id, n) WHERE t.id = v.id",
}
LOCK_KEY = "kb:hits:flush:lock"
BATCH = 1000


async def _apply(session: AsyncSession, kind: str, data: Mapping[Any, Any]) -> None:
    items = [(int(k), int(v)) for k, v in data.items() if v and int(v) > 0]
    for i in range(0, len(items), BATCH):
        chunk = items[i : i + BATCH]
        await session.execute(text(KINDS[kind]), {"ids": [c[0] for c in chunk], "ns": [c[1] for c in chunk]})


async def _process_key(redis: Redis, kind: str, key: str) -> int:
    data = await redis.hgetall(key)
    if data:
        async with get_session_factory()() as session:
            await _apply(session, kind, data)
            await session.commit()
    await redis.delete(key)
    return len(data)


async def flush_hits(redis: Redis | None = None) -> int:
    """执行一轮落库，返回处理的条目数（持锁失败返回 0）。"""
    r = redis or get_redis()
    token = uuid.uuid4().hex
    if not await r.set(LOCK_KEY, token, nx=True, ex=120):
        return 0
    total = 0
    try:
        for kind in KINDS:
            base = f"kb:hits:{kind}"
            leftovers = [k async for k in r.scan_iter(f"{base}:flush:*")]
            for key in leftovers:
                total += await _process_key(r, kind, key)
            tmp = f"{base}:flush:{uuid.uuid4().hex}"
            try:
                await r.rename(base, tmp)
            except ResponseError:  # 当前没有新计数（key 不存在）
                continue
            total += await _process_key(r, kind, tmp)
    finally:
        with contextlib.suppress(RedisError):
            if await r.get(LOCK_KEY) == token:
                await r.delete(LOCK_KEY)
    return total


async def run_hit_flush(settings: Settings) -> None:
    """后台循环：每 ``HIT_FLUSH_INTERVAL_SECONDS`` 秒落库一次；单轮失败只记日志。"""
    while True:
        try:
            n = await flush_hits()
            if n:
                logger.info("召回次数已落库", extra={"items": n})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("召回次数落库失败")
        await asyncio.sleep(settings.HIT_FLUSH_INTERVAL_SECONDS)
