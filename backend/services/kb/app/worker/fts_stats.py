"""大库全文检索的常见词表（tech-design-m2 3.10.4）。

对检索单元数超过 ``FULLTEXT_PRUNE_MIN_ROWS`` 的知识库，用 ``ts_stat`` 统计词的文档频率，
文档频率占比超过 ``FULLTEXT_COMMON_TERM_RATIO`` 的词写入 Redis 哈希 ``kb:fts:common:{dataset_id}``
（词 → 文档数，TTL 24 小时）。检索侧（``engine/fulltext.py``）据此把查询词拆为"稀有词/常见词"，裁剪打分候选。
10 万行约数秒，在 worker 中执行，不影响在线请求。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import case, select, text

from app.core.config import Settings, get_settings
from app.core.constants import ChunkMode
from app.engine.fulltext import COMMON_TERMS_SENTINEL, TASK_FTS_COMMON_TERMS, common_terms_key
from app.models import Dataset
from app.worker.tasks_document import TASK_HANDLERS
from platform_common.db import get_session_factory
from platform_common.jobs import run_periodic
from platform_common.redis import get_redis

logger = logging.getLogger("kb.worker.fts_stats")

TTL_SECONDS = 24 * 3600


def _ts_key(dataset_id: int) -> str:
    return f"kb:fts:common:ts:{int(dataset_id)}"


async def compute_common_terms(dataset_id: int, settings: Settings | None = None) -> int | None:
    """计算并写入常见词表，返回常见词数量；知识库不存在或不是大库返回 None。"""
    s = settings or get_settings()
    did = int(dataset_id)
    async with get_session_factory()() as session:
        dataset = (
            await session.execute(select(Dataset).where(Dataset.id == did, Dataset.is_deleted.is_(False)))
        ).scalar_one_or_none()
        if dataset is None:
            return None
        table = "child_chunk" if dataset.chunk_mode == ChunkMode.PARENT_CHILD else "segment"
        rows = int(
            (
                await session.execute(
                    text(f"SELECT count(*) FROM kb.{table} WHERE dataset_id = :d AND search_enabled"), {"d": did}
                )
            ).scalar_one()
        )
        if rows <= s.FULLTEXT_PRUNE_MIN_ROWS:
            return None
        started = time.perf_counter()
        # ts_stat 的参数是 SQL 文本：只拼入 int() 校验过的知识库 ID 与固定表名
        stat = await session.execute(
            text(
                "SELECT word, ndoc FROM ts_stat("
                f"$$SELECT tsv FROM kb.{table} WHERE dataset_id = {did} AND search_enabled$$)"
            )
        )
        threshold = rows * s.FULLTEXT_COMMON_TERM_RATIO
        common = {str(w): int(n) for w, n in stat.all() if n > threshold}
    r = get_redis()
    key = common_terms_key(did)
    pipe = r.pipeline()
    pipe.delete(key)
    pipe.hset(key, mapping={COMMON_TERMS_SENTINEL: "0", **{w: str(n) for w, n in common.items()}})
    pipe.expire(key, TTL_SECONDS)
    pipe.set(_ts_key(did), str(time.time()), ex=TTL_SECONDS)
    await pipe.execute()
    logger.info(
        "常见词表已更新",
        extra={
            "dataset_id": did,
            "rows": rows,
            "common_terms": len(common),
            "seconds": round(time.perf_counter() - started, 1),
        },
    )
    return len(common)


async def refresh_large_datasets(settings: Settings | None = None) -> int:
    """词表缺失、或知识库 ``updated_at`` 晚于上次计算的大库重新计算；返回计算个数。"""
    s = settings or get_settings()
    units = case(
        (Dataset.chunk_mode == ChunkMode.PARENT_CHILD, Dataset.child_segment_count), else_=Dataset.segment_count
    )
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(Dataset.id, Dataset.updated_at).where(
                    Dataset.is_deleted.is_(False), units > s.FULLTEXT_PRUNE_MIN_ROWS
                )
            )
        ).all()
    r = get_redis()
    done = 0
    for did, updated_at in rows:
        last = await r.get(_ts_key(int(did)))
        if last is not None and float(last) >= updated_at.timestamp() and await r.exists(common_terms_key(int(did))):
            continue
        try:
            if await compute_common_terms(int(did), s) is not None:
                done += 1
        except Exception:
            logger.error("常见词表计算失败", exc_info=True, extra={"dataset_id": int(did)})
    return done


async def handle_common_terms(envelope: dict[str, Any]) -> None:
    payload = envelope.get("payload") or {}
    await compute_common_terms(int(payload["dataset_id"]))


TASK_HANDLERS[TASK_FTS_COMMON_TERMS] = handle_common_terms


async def run_common_terms_refresh(settings: Settings | None = None) -> None:
    s = settings or get_settings()

    async def _tick() -> None:
        await refresh_large_datasets(s)

    await run_periodic("kb_fts_common_terms", s.FULLTEXT_COMMON_TERMS_REFRESH_SECONDS, _tick)
