"""向量检索存储抽象与 pgvector 实现（tech-design-m2 3.7、3.10.1）。

``VectorStore`` 是检索层的替换接口：将来换 Qdrant 等只需新增实现，``retriever`` 不感知。

``PgVectorStore`` 按知识库规模选择两条路径：

* **精确路径**：``WHERE dataset_id AND search_enabled ORDER BY embedding <=> q``，只读本库行（``ix_*_search``）。
  小库（检索单元 <= ``VECTOR_EXACT_MAX_ROWS``）、该模型的 HNSW 索引不存在/无效、维度 > 4000 时使用；
* **HNSW 路径**：全平台共享一个"按模型划分"的 halfvec HNSW 部分索引（由 kb-worker 运行时创建，见
  ``app/worker/vector_index.py``），迭代扫描 + 按本库占比放大的扫描上限；返回条数不足时回退精确路径。

模型 ID 与维度以**整数字面量**写入 SQL（来自服务端模型表，经 ``int()`` 校验，非用户输入），
这样规划器才能证明命中部分索引的谓词与表达式；向量、知识库 ID、LIMIT 仍为绑定参数。
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Select, Text, bindparam, cast, literal_column, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.base import Executable
from sqlalchemy.sql.elements import ClauseElement

from app.core.config import Settings, get_settings
from app.models import ChildChunk, Segment

logger = logging.getLogger("kb.engine.vector")

UnitTable = Literal["segment", "child_chunk"]

# halfvec HNSW 索引的维度上限（pgvector）；超过则不建索引、只走精确路径
HNSW_MAX_DIMENSION = 4000
INDEX_PREFIX: dict[UnitTable, str] = {"segment": "ix_seg_hnsw_m", "child_chunk": "ix_child_hnsw_m"}
INDEX_CACHE_TTL_SECONDS = 60.0
HNSW_EF_SEARCH_CAP = 1000
METRIC_HNSW_FALLBACK = "kb:metrics:hnsw_fallback"

# 进程内计数（压测脚本读取）；同时尽力累加 Redis 计数
METRICS: Counter[str] = Counter()


def unit_model(table: UnitTable) -> type[Segment] | type[ChildChunk]:
    return ChildChunk if table == "child_chunk" else Segment


def to_score(distance: float) -> float:
    """余弦距离 → 相似度得分，限制在 [0, 1]。"""
    return max(0.0, min(1.0, 1.0 - float(distance)))


async def bump_metric(name: str) -> None:
    """计数 +1：进程内 + Redis（Redis 不可用时忽略）。"""
    METRICS[name] += 1
    try:
        from platform_common.redis import get_redis

        await get_redis().incr(name)
    except Exception:
        logger.debug("指标累加失败", exc_info=True, extra={"metric": name})


class Explain(Executable, ClauseElement):
    """``EXPLAIN <stmt>``：测试与压测用来断言索引命中。"""

    inherit_cache = False

    def __init__(self, stmt: Select[Any]) -> None:
        self.stmt = stmt


@compiles(Explain)
def _compile_explain(element: Explain, compiler: Any, **kw: Any) -> str:
    return "EXPLAIN " + str(compiler.process(element.stmt, **kw))


# ---------------------------------------------------------------- HNSW 索引可用性（进程内缓存）


@dataclass(frozen=True)
class IndexInfo:
    dimension: int
    rows: float  # 索引行数估计（pg_class.reltuples）


_index_cache: dict[UnitTable, tuple[float, dict[int, IndexInfo]]] = {}
_DIM_RE = re.compile(r"halfvec\((\d+)\)")


def reset_index_cache() -> None:
    _index_cache.clear()


async def valid_indexes(session: AsyncSession, table: UnitTable, *, use_cache: bool = True) -> dict[int, IndexInfo]:
    """该表上有效（indisvalid 且 indisready）的 HNSW 索引：模型 ID → (维度, 行数估计)；缓存 60 秒。"""
    now = time.monotonic()
    cached = _index_cache.get(table)
    if use_cache and cached is not None and now - cached[0] < INDEX_CACHE_TTL_SECONDS:
        return cached[1]
    prefix = INDEX_PREFIX[table]
    rows = (
        await session.execute(
            text(
                "SELECT c.relname, pg_get_indexdef(i.indexrelid), c.reltuples::float8 "
                "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'kb' AND c.relname LIKE :pat AND i.indisvalid AND i.indisready"
            ),
            {"pat": prefix.replace("_", "\\_") + "%"},
        )
    ).all()
    result: dict[int, IndexInfo] = {}
    for relname, indexdef, reltuples in rows:
        suffix = str(relname)[len(prefix) :]
        m = _DIM_RE.search(str(indexdef))
        if suffix.isdigit() and m:
            result[int(suffix)] = IndexInfo(int(m.group(1)), float(reltuples))
    _index_cache[table] = (now, result)
    return result


# ---------------------------------------------------------------- 抽象与实现


class VectorStore(Protocol):
    async def search(
        self, dataset_id: int, table: UnitTable, query_vector: Sequence[float], limit: int
    ) -> list[tuple[int, float]]:
        """返回 (单元 ID, 得分) 列表，按得分降序、同分 ID 升序，最多 ``limit`` 条。"""
        ...

    async def score_by_ids(
        self, dataset_id: int, table: UnitTable, query_vector: Sequence[float], ids: Sequence[int]
    ) -> dict[int, float]:
        """对指定的单元 ID 计算得分（混合检索补算另一路缺失的得分）；不可检索的 ID 不在结果中。"""
        ...


def hnsw_max_scan_tuples(limit: int, index_rows: float, units: int, settings: Settings) -> int:
    """``clamp(ceil(2 × n × total_m / units), MIN, MAX)``：按本库在索引中的占比放大扫描上限。"""
    raw = math.ceil(2 * limit * max(index_rows, float(units)) / max(units, 1))
    return max(settings.HNSW_MAX_SCAN_TUPLES_MIN, min(settings.HNSW_MAX_SCAN_TUPLES_MAX, raw))


class PgVectorStore:
    """``model_id`` / ``dimension`` / ``units`` 任一缺失（如单测直接构造）则只走精确路径。"""

    def __init__(
        self,
        session: AsyncSession,
        *,
        model_id: int | None = None,
        dimension: int | None = None,
        units: int | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._model_id = int(model_id) if model_id is not None else None
        self._dimension = int(dimension) if dimension is not None else None
        self._units = int(units) if units is not None else None
        self._settings = settings or get_settings()

    # ------------------------------------------------------------ 路径选择

    async def hnsw_info(self, table: UnitTable) -> IndexInfo | None:
        """走 HNSW 路径所需的索引信息；不满足条件（小库/无索引/维度不符/维度 > 4000）返回 None。"""
        if self._model_id is None or self._dimension is None or self._units is None:
            return None
        if self._units <= self._settings.VECTOR_EXACT_MAX_ROWS or self._dimension > HNSW_MAX_DIMENSION:
            return None
        info = (await valid_indexes(self._session, table)).get(self._model_id)
        if info is None or info.dimension != self._dimension:
            return None
        return info

    async def search(
        self, dataset_id: int, table: UnitTable, query_vector: Sequence[float], limit: int
    ) -> list[tuple[int, float]]:
        info = await self.hnsw_info(table)
        if info is None:
            return await self.search_exact(dataset_id, table, query_vector, limit)
        assert self._units is not None
        rows = await self.search_hnsw(dataset_id, table, query_vector, limit, info)
        if len(rows) < min(limit, self._units):
            logger.warning(
                "HNSW 返回条数不足，回退精确检索",
                extra={"dataset_id": dataset_id, "table": table, "got": len(rows), "want": limit, "units": self._units},
            )
            await bump_metric(METRIC_HNSW_FALLBACK)
            return await self.search_exact(dataset_id, table, query_vector, limit)
        return rows

    # ------------------------------------------------------------ 精确路径

    def exact_stmt(self, dataset_id: int, table: UnitTable, query_vector: Sequence[float], limit: int) -> Select[Any]:
        t = unit_model(table)
        dist = t.embedding.cosine_distance(list(query_vector))
        return (
            select(t.id, dist.label("dist"))
            .where(t.dataset_id == dataset_id, t.search_enabled)
            .order_by(dist, t.id)
            .limit(limit)
        )

    async def search_exact(
        self, dataset_id: int, table: UnitTable, query_vector: Sequence[float], limit: int
    ) -> list[tuple[int, float]]:
        rows = (await self._session.execute(self.exact_stmt(dataset_id, table, query_vector, limit))).all()
        return [(int(r[0]), to_score(r[1])) for r in rows]

    # ------------------------------------------------------------ HNSW 路径

    def hnsw_stmt(
        self, dataset_id: int, table: UnitTable, query_vector: Sequence[float], limit: int, dimension: int
    ) -> Select[Any]:
        """表达式与索引定义完全一致：``(embedding::halfvec(dim)) <=> q``，谓词含整数字面量 model_id。"""
        assert self._model_id is not None
        t = unit_model(table)
        emb = cast(t.embedding, HALFVEC(int(dimension)))
        dist = emb.cosine_distance(list(query_vector))
        return (
            select(t.id, dist.label("dist"))
            .where(
                t.search_enabled,  # 必须是裸布尔列，不能 .is_(True)（否则规划器证明不了部分索引谓词）
                t.embedding_model_id == literal_column(str(int(self._model_id))),
                t.dataset_id == dataset_id,
            )
            .order_by(dist)
            .limit(limit)
        )

    async def _set_hnsw_params(self, limit: int, index_rows: float) -> None:
        s = self._settings
        assert self._units is not None
        ef = min(HNSW_EF_SEARCH_CAP, max(s.HNSW_EF_SEARCH, limit))
        scan = hnsw_max_scan_tuples(limit, index_rows, self._units, s)
        stmt = text(
            "SELECT set_config('hnsw.ef_search', :ef, true), set_config('hnsw.iterative_scan', 'relaxed_order', true), "
            "set_config('hnsw.max_scan_tuples', :scan, true)"
        ).bindparams(bindparam("ef", type_=Text), bindparam("scan", type_=Text))
        await self._session.execute(stmt, {"ef": str(ef), "scan": str(scan)})

    async def search_hnsw(
        self, dataset_id: int, table: UnitTable, query_vector: Sequence[float], limit: int, info: IndexInfo
    ) -> list[tuple[int, float]]:
        await self._set_hnsw_params(limit, info.rows)
        stmt = self.hnsw_stmt(dataset_id, table, query_vector, limit, info.dimension)
        rows = (await self._session.execute(stmt)).all()
        # relaxed_order 的结果可能轻微乱序：按（距离，ID）重排
        ordered = sorted(((float(r[1]), int(r[0])) for r in rows), key=lambda x: (x[0], x[1]))
        return [(i, to_score(d)) for d, i in ordered]

    async def explain(
        self, dataset_id: int, table: UnitTable, query_vector: Sequence[float], limit: int, *, hnsw: bool
    ) -> str:
        """对应路径的 EXPLAIN 文本（测试/压测断言索引命中）。HNSW 路径需 ``hnsw_info`` 可用。"""
        await self._session.execute(text("SET LOCAL plan_cache_mode = force_custom_plan"))
        if hnsw:
            info = await valid_indexes(self._session, table, use_cache=False)
            assert self._model_id is not None
            idx = info[self._model_id]
            await self._set_hnsw_params(limit, idx.rows)
            stmt = self.hnsw_stmt(dataset_id, table, query_vector, limit, idx.dimension)
        else:
            stmt = self.exact_stmt(dataset_id, table, query_vector, limit)
        rows = (await self._session.execute(Explain(stmt))).scalars().all()
        return "\n".join(str(r) for r in rows)

    # ------------------------------------------------------------ 补算

    async def score_by_ids(
        self, dataset_id: int, table: UnitTable, query_vector: Sequence[float], ids: Sequence[int]
    ) -> dict[int, float]:
        if not ids:
            return {}
        t = unit_model(table)
        dist = t.embedding.cosine_distance(list(query_vector))
        stmt = select(t.id, dist.label("dist")).where(t.dataset_id == dataset_id, t.search_enabled, t.id.in_(list(ids)))
        return {int(r[0]): to_score(r[1]) for r in (await self._session.execute(stmt)).all()}


__all__ = [
    "HNSW_MAX_DIMENSION",
    "INDEX_PREFIX",
    "METRICS",
    "Explain",
    "IndexInfo",
    "PgVectorStore",
    "UnitTable",
    "VectorStore",
    "hnsw_max_scan_tuples",
    "reset_index_cache",
    "to_score",
    "unit_model",
    "valid_indexes",
]
