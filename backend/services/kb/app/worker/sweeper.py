"""巡检（每 ``SWEEP_INTERVAL_SECONDS`` 秒，单实例）：处理超时、排队消息丢失重投（TQ-01）。"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.exceptions import ResponseError

from app.core.config import Settings, get_settings
from app.core.constants import TASK_STREAM
from app.repositories import document_repo
from app.services import segment_service, stats_service
from app.worker.main_loop import GROUP
from app.worker.tasks_document import TASK_DOCUMENT_PROCESS
from platform_common.db import get_session_factory
from platform_common.events.publisher import publish
from platform_common.events.streams import MESSAGE_FIELD
from platform_common.jobs import run_periodic
from platform_common.redis import get_redis

logger = logging.getLogger("kb.worker.sweeper")

MAX_SCAN = 5000
REDELIVER_BATCH = 200


async def fail_timed_out_documents(settings: Settings, now: datetime | None = None) -> int:
    """解析中/分段中/索引中且无进度超过 PROCESS_TIMEOUT_MINUTES → failed(TIMEOUT)，attempt+1 使在途旧任务失效。"""
    cutoff = (now or datetime.now(UTC)) - timedelta(minutes=settings.PROCESS_TIMEOUT_MINUTES)
    async with get_session_factory()() as s:
        dataset_ids = await document_repo.timed_out_dataset_ids(s, cutoff)
    total = 0
    for dataset_id in dataset_ids:
        async with get_session_factory()() as s:
            if not await document_repo.lock_dataset_row(s, dataset_id):
                continue
            ids = await document_repo.fail_timed_out(s, dataset_id, cutoff)
            await s.flush()
            for doc_id in ids:
                await segment_service.refresh_search_flags(s, doc_id)
            if ids:
                await stats_service.recalc_dataset(s, dataset_id)
            await s.commit()
        total += len(ids)
        if ids:
            logger.warning("文档处理超时", extra={"dataset_id": dataset_id, "document_ids": ids})
    return total


async def inflight_tasks() -> set[tuple[int, int]]:
    """队列中仍待处理的 ``document.process`` 任务 ``(document_id, attempt)``：未投递给消费组的 + 已投递未确认的。"""
    r = get_redis()
    try:
        groups = await r.xinfo_groups(TASK_STREAM)
    except ResponseError:  # 流不存在
        return set()
    group = next((g for g in groups if g.get("name") == GROUP), None)
    entries: list[Any] = []
    if group is None:  # 消费组尚未创建：全部消息都在等待
        entries += await r.xrange(TASK_STREAM, "-", "+", count=MAX_SCAN) or []
    else:
        last = group.get("last-delivered-id", "0-0")
        entries += await r.xrange(TASK_STREAM, f"({last}", "+", count=MAX_SCAN) or []
        pending = await r.xpending_range(TASK_STREAM, GROUP, "-", "+", MAX_SCAN)
        if pending:
            ids = {p["message_id"] for p in pending}
            span: list[Any] = (
                await r.xrange(TASK_STREAM, pending[0]["message_id"], pending[-1]["message_id"], count=MAX_SCAN) or []
            )
            entries += [(mid, f) for mid, f in span if mid in ids]
    result: set[tuple[int, int]] = set()
    for _, fields in entries:
        try:
            body: dict[str, Any] = json.loads(fields[MESSAGE_FIELD])
            if body.get("type") == TASK_DOCUMENT_PROCESS:
                p = body["payload"]
                result.add((int(p["document_id"]), int(p["attempt"])))
        except (KeyError, ValueError, TypeError):
            continue
    return result


async def redeliver_stale_queued(settings: Settings, now: datetime | None = None) -> int:
    """排队中超过 QUEUED_REDELIVER_MINUTES 且队列里没有对应消息 → 重新投递；有消息则继续等待（不计入处理超时）。"""
    cutoff = (now or datetime.now(UTC)) - timedelta(minutes=settings.QUEUED_REDELIVER_MINUTES)
    async with get_session_factory()() as s:
        stale = await document_repo.stale_queued(s, cutoff, REDELIVER_BATCH)
        rows = [(d.id, d.process_attempt, d.failed_stage or "parse") for d in stale]
    if not rows:
        return 0
    inflight = await inflight_tasks()
    count = 0
    for doc_id, attempt, stage in rows:
        if (doc_id, attempt) in inflight:
            continue
        await publish(
            TASK_STREAM, TASK_DOCUMENT_PROCESS, {"document_id": doc_id, "attempt": attempt, "from_stage": stage}
        )
        async with get_session_factory()() as s:
            await document_repo.touch_queued(s, doc_id, attempt)
            await s.commit()
        count += 1
        logger.warning("排队消息缺失，已重新投递", extra={"document_id": doc_id, "attempt": attempt})
    return count


async def sweep_once(settings: Settings | None = None) -> None:
    s = settings or get_settings()
    await fail_timed_out_documents(s)
    await redeliver_stale_queued(s)


async def run_sweeper(settings: Settings | None = None) -> None:
    s = settings or get_settings()

    async def _tick() -> None:
        await sweep_once(s)

    await run_periodic("kb_sweeper", s.SWEEP_INTERVAL_SECONDS, _tick)
