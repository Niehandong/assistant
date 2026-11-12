"""HNSW 向量索引的运行时创建与对账（tech-design-m2 3.10.2；CLAUDE.md 4.4 登记的规范例外）。

索引依赖模型 ID 与维度，迁移无法预知，因此由 kb-worker 在运行时创建，仅限两类索引：
``ix_seg_hnsw_m{model_id}`` / ``ix_child_hnsw_m{model_id}``（halfvec HNSW 部分索引，谓词含整数字面量模型 ID）。

* ``CREATE/DROP INDEX CONCURRENTLY`` 不能在事务中执行：使用独立的 autocommit 连接；
* 同一模型的建/删索引由 Redis 锁 ``kb:vindex:lock:{model_id}``（TTL 2 小时）串行，避免多 worker 并发，
  也避免对账误删另一个 worker 正在构建（尚未生效）的索引；
* 对账：未删除且维度 <= 4000 的 Embedding 模型确保两个有效索引；无效索引（中断留下的）先 ``DROP`` 再重建；
  维度与索引表达式不一致则重建；已删除/不再适用模型的索引删除。
* 检索侧发现索引缺失/无效会自动走精确路径，因此索引问题只影响性能，不影响正确性。

模型 ID、维度以 ``int()`` 校验后写入 DDL（来自服务端模型表，非用户输入）。
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import Settings, get_settings
from app.core.constants import ModelType
from app.engine.vector_store import HNSW_MAX_DIMENSION, INDEX_PREFIX, UnitTable, reset_index_cache
from app.models import AiModel
from app.worker.tasks_document import TASK_HANDLERS
from platform_common.db import get_engine, get_session_factory
from platform_common.jobs import run_periodic
from platform_common.redis import get_redis

logger = logging.getLogger("kb.worker.vector_index")

TASK_ENSURE_INDEX = "vector.ensure_index"
LOCK_KEY = "kb:vindex:lock:{model_id}"
LOCK_TTL_SECONDS = 7200
TABLES: dict[UnitTable, str] = {"segment": "kb.segment", "child_chunk": "kb.child_chunk"}
_DIM_RE = re.compile(r"halfvec\((\d+)\)")
_RELEASE_LUA = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0"


@dataclass(frozen=True)
class ExistingIndex:
    table: UnitTable
    name: str
    model_id: int
    valid: bool
    dimension: int | None


def index_name(table: UnitTable, model_id: int) -> str:
    return f"{INDEX_PREFIX[table]}{int(model_id)}"


def create_index_sql(table: UnitTable, model_id: int, dimension: int, settings: Settings) -> str:
    """``CREATE INDEX CONCURRENTLY``：表达式与谓词必须与检索 SQL（vector_store.hnsw_stmt）完全一致。"""
    mid, dim = int(model_id), int(dimension)
    return (
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name(table, mid)} ON {TABLES[table]} "
        f"USING hnsw ((embedding::halfvec({dim})) halfvec_cosine_ops) "
        f"WITH (m = {int(settings.HNSW_M)}, ef_construction = {int(settings.HNSW_EF_CONSTRUCTION)}) "
        f"WHERE search_enabled AND embedding_model_id = {mid}"
    )


async def list_existing(conn: AsyncConnection) -> list[ExistingIndex]:
    rows = (
        await conn.execute(
            text(
                "SELECT c.relname, pg_get_indexdef(i.indexrelid), (i.indisvalid AND i.indisready) "
                "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'kb' AND (c.relname LIKE :p1 OR c.relname LIKE :p2)"
            ),
            {
                "p1": INDEX_PREFIX["segment"].replace("_", "\\_") + "%",
                "p2": INDEX_PREFIX["child_chunk"].replace("_", "\\_") + "%",
            },
        )
    ).all()
    result: list[ExistingIndex] = []
    for relname, indexdef, valid in rows:
        name = str(relname)
        table: UnitTable = "segment" if name.startswith(INDEX_PREFIX["segment"]) else "child_chunk"
        suffix = name[len(INDEX_PREFIX[table]) :]
        if not suffix.isdigit():
            continue
        m = _DIM_RE.search(str(indexdef))
        result.append(ExistingIndex(table, name, int(suffix), bool(valid), int(m.group(1)) if m else None))
    return result


async def active_models(model_id: int | None = None) -> dict[int, int]:
    """应当拥有 HNSW 索引的模型：未删除的 Embedding 模型、维度 1~4000 → {模型 ID: 维度}。"""
    stmt = select(AiModel.id, AiModel.dimension).where(
        AiModel.is_deleted.is_(False),
        AiModel.model_type == ModelType.EMBEDDING,
        AiModel.dimension.is_not(None),
        AiModel.dimension >= 1,
        AiModel.dimension <= HNSW_MAX_DIMENSION,
    )
    if model_id is not None:
        stmt = stmt.where(AiModel.id == model_id)
    async with get_session_factory()() as s:
        return {int(i): int(d) for i, d in (await s.execute(stmt)).all()}


async def _acquire(model_id: int) -> str | None:
    token = uuid.uuid4().hex
    ok = await get_redis().set(LOCK_KEY.format(model_id=model_id), token, nx=True, ex=LOCK_TTL_SECONDS)
    return token if ok else None


async def _release(model_id: int, token: str) -> None:
    await get_redis().eval(_RELEASE_LUA, 1, LOCK_KEY.format(model_id=model_id), token)


async def _drop(conn: AsyncConnection, name: str) -> None:
    logger.info("删除向量索引", extra={"index": name})
    await conn.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS kb.{name}"))


async def _reconcile_model(
    conn: AsyncConnection, model_id: int, dimension: int | None, settings: Settings
) -> dict[str, Any]:
    """在持有该模型锁的前提下对账：dimension 为 None 表示模型不应有索引（全部删除）。"""
    summary: dict[str, Any] = {"model_id": model_id, "dropped": [], "created": []}
    existing = [e for e in await list_existing(conn) if e.model_id == model_id]
    keep: set[UnitTable] = set()
    for e in existing:
        if dimension is None or not e.valid or e.dimension != dimension:
            await _drop(conn, e.name)
            summary["dropped"].append(e.name)
        else:
            keep.add(e.table)
    if dimension is not None:
        for table in TABLES:
            if table in keep:
                continue
            started = time.perf_counter()
            await conn.execute(text(create_index_sql(table, model_id, dimension, settings)))
            size = (
                await conn.execute(
                    text("SELECT pg_relation_size(to_regclass(:n))"), {"n": f"kb.{index_name(table, model_id)}"}
                )
            ).scalar()
            elapsed = round(time.perf_counter() - started, 1)
            logger.info(
                "向量索引已创建",
                extra={"index": index_name(table, model_id), "seconds": elapsed, "size_bytes": size},
            )
            summary["created"].append({"index": index_name(table, model_id), "seconds": elapsed, "size_bytes": size})
    return summary


async def reconcile(model_id: int | None = None, settings: Settings | None = None) -> list[dict[str, Any]]:
    """对账全部模型（``model_id=None``）或单个模型；返回每个被处理模型的摘要（拿不到锁的模型跳过）。"""
    s = settings or get_settings()
    active = await active_models(model_id)
    engine = get_engine()
    async with engine.connect() as probe:
        existing_ids = {e.model_id for e in await list_existing(probe)}
    targets = set(active) | existing_ids if model_id is None else {model_id}
    results: list[dict[str, Any]] = []
    for mid in sorted(targets):
        token = await _acquire(mid)
        if token is None:
            logger.info("模型的索引维护正在进行（锁被占用），本轮跳过", extra={"model_id": mid})
            continue
        try:
            async with engine.connect() as conn:
                conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
                results.append(await _reconcile_model(conn, mid, active.get(mid), s))
        except Exception:
            logger.error("向量索引对账失败", exc_info=True, extra={"model_id": mid})
        finally:
            await _release(mid, token)
    reset_index_cache()
    return results


async def handle_ensure_index(envelope: dict[str, Any]) -> None:
    payload = envelope.get("payload") or {}
    await reconcile(int(payload["model_id"]))


TASK_HANDLERS[TASK_ENSURE_INDEX] = handle_ensure_index


async def run_vector_index_reconcile(settings: Settings | None = None) -> None:
    """worker 启动时立即对账一次，之后每 ``VECTOR_INDEX_RECONCILE_SECONDS`` 秒（单实例）。"""
    s = settings or get_settings()

    async def _tick() -> None:
        await reconcile(None, s)

    try:  # 启动即对账（不受单实例锁限制：重启后不必等下一个周期）；各模型的建/删索引另有 Redis 锁
        await reconcile(None, s)
    except Exception:
        logger.error("启动时向量索引对账失败", exc_info=True)
    await run_periodic("kb_vector_index_reconcile", s.VECTOR_INDEX_RECONCILE_SECONDS, _tick)
