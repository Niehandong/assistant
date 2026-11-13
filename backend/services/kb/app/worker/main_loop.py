"""任务消费者：``stream:kb.tasks`` 消费组 ``kb-doc-worker``，``WORKER_CONCURRENCY`` 个消费者并发处理。"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from app.core.config import Settings, get_settings
from app.core.constants import TASK_STREAM
from app.worker import fts_stats, tasks_segment, vector_index  # noqa: F401  # 导入即注册 segment.reindex、vector.ensure_index 等任务处理器
from app.worker.tasks_document import handle_task
from platform_common.events.consumer import StreamConsumer

logger = logging.getLogger("kb.worker.tasks")

GROUP = "kb-doc-worker"


def make_consumer(settings: Settings, name: str | None = None) -> StreamConsumer:
    return StreamConsumer(
        TASK_STREAM,
        GROUP,
        handle_task,
        batch=1,
        claim_idle_ms=settings.TASK_CLAIM_IDLE_SECONDS * 1000,
        consumer_name=name,
    )


async def run_task_consumers(settings: Settings | None = None) -> None:
    """并发运行多个消费者；被取消时先请求优雅停止（等待在途任务最多 10 秒）。"""
    s = settings or get_settings()
    consumers = [make_consumer(s) for _ in range(max(1, s.WORKER_CONCURRENCY))]
    inner = [asyncio.create_task(c.run_forever()) for c in consumers]
    try:
        await asyncio.shield(asyncio.gather(*inner))
    except asyncio.CancelledError:
        for c in consumers:
            await c.stop()
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError, Exception):
            await asyncio.wait_for(asyncio.gather(*inner, return_exceptions=True), timeout=10)
        for t in inner:
            t.cancel()
        raise
