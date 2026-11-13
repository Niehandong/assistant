"""kb-worker 入口：``cd backend/services/kb && ../../../.venv/bin/python worker.py``。

初始化 DB/Redis、等待退出信号并优雅关闭；iam 事件同步（BE-12）、文档处理任务消费、超时/排队巡检、
上传清理（BE-18）通过 ``register`` 注册为后台协程。
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable, Coroutine
from typing import Any

from app.core.config import Settings, get_settings
from app.parsers.registry import shutdown_pool
from app.worker import fts_stats, hit_flush, ref_sync, sweeper, upload_cleanup, vector_index
from app.worker.main_loop import run_task_consumers
from platform_common.auth import runtime
from platform_common.db import dispose_db, init_db
from platform_common.logging import setup_logging
from platform_common.redis import close_redis, init_redis

logger = logging.getLogger("kb.worker")

# 后台协程工厂：由后续任务追加，返回一个会一直运行直到被取消的协程
BackgroundFactory = Callable[[], Coroutine[Any, Any, None]]
BACKGROUND_FACTORIES: list[tuple[str, BackgroundFactory]] = []


def register(name: str, factory: BackgroundFactory) -> None:
    BACKGROUND_FACTORIES.append((name, factory))


async def run(settings: Settings, stop: asyncio.Event | None = None) -> None:
    """运行 worker 直到 ``stop`` 被置位（或收到 SIGINT/SIGTERM）。"""
    setup_logging(settings.SERVICE_NAME + "-worker", settings.LOG_LEVEL)
    settings.validate_for_runtime()
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    init_db(settings)
    init_redis(settings)
    runtime.configure(settings)  # iam 内部客户端（副本同步）
    tasks: list[asyncio.Task[None]] = [
        asyncio.create_task(factory(), name=name) for name, factory in BACKGROUND_FACTORIES
    ]
    logger.info("kb-worker 已启动", extra={"background_tasks": len(tasks)})
    try:
        await stop.wait()
    finally:
        logger.info("kb-worker 正在退出")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await runtime.shutdown()
        shutdown_pool()
        await close_redis()
        await dispose_db()
        logger.info("kb-worker 已退出")


def register_defaults(settings: Settings) -> None:
    """注册 worker 的内置后台任务（幂等）。"""
    names = {n for n, _ in BACKGROUND_FACTORIES}
    if "ref-sync-consumer" not in names:
        register("ref-sync-consumer", ref_sync.run_event_consumer)
    if "ref-reconcile" not in names:
        register("ref-reconcile", lambda: ref_sync.run_reconcile(settings))
    if "document-tasks" not in names:
        register("document-tasks", lambda: run_task_consumers(settings))
    if "sweeper" not in names:
        register("sweeper", lambda: sweeper.run_sweeper(settings))
    if "hit-flush" not in names:
        register("hit-flush", lambda: hit_flush.run_hit_flush(settings))
    if "vector-index-reconcile" not in names:
        register("vector-index-reconcile", lambda: vector_index.run_vector_index_reconcile(settings))
    if "fts-common-terms" not in names:
        register("fts-common-terms", lambda: fts_stats.run_common_terms_refresh(settings))
    if "upload-cleanup" not in names:
        register("upload-cleanup", lambda: upload_cleanup.run_upload_cleanup(settings))


def main() -> None:
    settings = get_settings()
    register_defaults(settings)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
