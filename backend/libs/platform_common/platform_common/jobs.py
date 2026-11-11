"""单实例定时任务：基于 Redis ``SET NX EX`` 的轻量调度。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from platform_common.auth.cache_keys import job_lock
from platform_common.redis import get_redis

logger = logging.getLogger(__name__)


async def run_periodic(
    name: str,
    interval_seconds: int,
    func: Callable[[], Awaitable[None]],
    *,
    singleton: bool = True,
) -> None:
    """每 ``interval_seconds`` 执行一次 ``func``，直到被取消。

    ``singleton=True`` 时每轮先抢 ``job:lock:{name}``（TTL=间隔），多实例同一周期内只有一个执行。
    ``func`` 抛出的异常只记录日志，不终止循环。
    """
    while True:
        try:
            if not singleton or await get_redis().set(job_lock(name), "1", nx=True, ex=interval_seconds):
                await func()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("定时任务执行失败", extra={"job": name})
        await asyncio.sleep(interval_seconds)
