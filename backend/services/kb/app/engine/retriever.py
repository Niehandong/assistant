"""检索引擎入口（tech-design-m2 3.7）。

``retrieve(...)`` 不依赖 HTTP、ACL、模型表：调用方（``retrieval_service``）负责校验知识库访问与模型状态、
构造 ``embed_query`` / ``reranker``，引擎只负责"候选 → 打分 → 重排 → 阈值 → 父子聚合 → 组装"。
BE-22（内部检索接口）应调用 ``retrieval_service.search``，而不是直接调用本函数。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.constants import ChunkMode
from app.engine.fulltext import (
    build_terms_async,
    fulltext_scores_by_ids,
    fulltext_search,
    fulltext_search_pruned,
    load_common_terms,
    request_common_terms,
    terms_to_tsquery,
)
from app.engine.rerank import RERANK_SKIPPED_REASON, Reranker
from app.engine.vector_store import PgVectorStore, UnitTable, VectorStore
from app.repositories import retrieval_repo
from app.repositories.retrieval_repo import UnitRow
from app.schemas.dataset import RetrievalConfig
from app.schemas.retrieval import RecallChildChunk, RecallDocument, RecallRecord

SKIPPED_HYBRID_WEIGHT = 0.7  # 混合检索的 Rerank 不可用时退化为权重模式使用的语义权重
EmbedQuery = Callable[[str], Awaitable[Sequence[float]]]
SessionFactory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True)
class RetrievalOutcome:
    records: list[RecallRecord]
    rerank_skipped: bool
    rerank_skipped_reason: str | None


def candidate_limit(config: RetrievalConfig, *, parent_child: bool, rerank: bool, cap: int) -> int:
    """候选数 n：混合或重排 = min(max(top_k×4, 20), cap)；否则通用 = top_k，父子 = min(top_k×5, cap)。"""
    if config.search_method == "hybrid" or rerank:
        return min(max(config.top_k * 4, 20), cap)
    return min(config.top_k * 5, cap) if parent_child else config.top_k


async def _both[A, B](a: Awaitable[A], b: Awaitable[B]) -> tuple[A, B]:
    """并发执行两个协程；任一失败则取消另一个并抛出该异常（避免留下后台任务）。"""
    ta, tb = asyncio.ensure_future(a), asyncio.ensure_future(b)
    try:
        await asyncio.wait({ta, tb}, return_when=asyncio.FIRST_EXCEPTION)
    except BaseException:  # 包括外层取消
        for t in (ta, tb):
            t.cancel()
        await asyncio.gather(ta, tb, return_exceptions=True)
        raise
    for t in (ta, tb):
        if t.done() and not t.cancelled() and t.exception() is not None:
            other = tb if t is ta else ta
            other.cancel()
            await asyncio.gather(other, return_exceptions=True)
            raise t.exception()  # type: ignore[misc]
    return ta.result(), tb.result()


async def retrieve(
    session: AsyncSession,
    *,
    dataset_id: int,
    chunk_mode: str | None,
    query: str,
    config: RetrievalConfig,
    embed_query: EmbedQuery,
    reranker: Reranker | None = None,
    store: VectorStore | None = None,
    candidate_max: int = 100,
    embedding_model_id: int | None = None,
    dimension: int | None = None,
    units: int | None = None,
    session_factory: SessionFactory | None = None,
    settings: Settings | None = None,
) -> RetrievalOutcome:
    """在一个知识库内检索。

    参数：
    * ``chunk_mode``：``parent_child`` 检索子块并按父块聚合，其余按通用分段检索；
    * ``config``：生效的检索设置（已规范化）；
    * ``embed_query``：返回查询向量的协程函数（仅向量/混合检索调用；缓存由调用方实现）；
    * ``reranker``：``config.needs_rerank_model()`` 为真但传 ``None`` 表示重排模型不可用，
      引擎跳过重排（混合检索退化为权重 0.7），结果 ``rerank_skipped=True``；
    * ``store``：向量存储实现，缺省 ``PgVectorStore``；
    * ``embedding_model_id`` / ``dimension`` / ``units``（该库检索单元数）：用于向量路径选择（精确 / HNSW）与
      全文大库裁剪，缺失则一律走精确 + 不裁剪；
    * ``session_factory``：给出时混合检索的两路使用独立会话并发执行，未给出则串行（结果一致）。
    返回 ``RetrievalOutcome``，records 已按得分降序（同分 ID 升序），最多 ``top_k`` 条（父子按父块计）。
    模型调用失败抛 ``ModelClientError``（由调用方映射 503301）。
    """
    s = settings or get_settings()
    # 让规划器看到实际参数（按参数选择部分索引/常量折叠 tsquery），而不是复用通用计划；SET LOCAL 随事务结束失效
    await session.execute(text("SET LOCAL plan_cache_mode = force_custom_plan"))
    parent_child = chunk_mode == ChunkMode.PARENT_CHILD
    table: UnitTable = "child_chunk" if parent_child else "segment"
    store = store or PgVectorStore(session, model_id=embedding_model_id, dimension=dimension, units=units, settings=s)
    want_rerank = config.needs_rerank_model()
    skipped = want_rerank and reranker is None
    use_rerank = want_rerank and reranker is not None
    method = config.search_method
    n = candidate_limit(config, parent_child=parent_child, rerank=use_rerank, cap=candidate_max)
    prune = units is not None and units > s.FULLTEXT_PRUNE_MIN_ROWS

    async def vector_branch() -> tuple[Sequence[float], dict[int, float]]:
        qv = await embed_query(query)
        return qv, dict(await store.search(dataset_id, table, qv, n))

    async def fulltext_branch(sess: AsyncSession) -> tuple[str | None, dict[int, float]]:
        if sess is not session:
            await sess.execute(text("SET LOCAL plan_cache_mode = force_custom_plan"))
        terms = await build_terms_async(query)
        if not terms:
            return None, {}
        if prune:
            common = await load_common_terms(dataset_id)
            if common is None:
                await request_common_terms(dataset_id)
            hits = await fulltext_search_pruned(sess, dataset_id, table, terms, n, common=common, settings=s)
        else:
            hits = await fulltext_search(sess, dataset_id, table, terms_to_tsquery(terms), n)
        return terms_to_tsquery(terms), dict(hits)

    vec: dict[int, float] = {}
    kw: dict[int, float] = {}
    tsq: str | None = None
    qv: Sequence[float] = []
    async with contextlib.AsyncExitStack() as stack:
        # 混合检索：向量路与全文路各用一个会话并发；其余方式单路
        ft_session = session
        if method == "hybrid" and session_factory is not None:
            ft_session = await stack.enter_async_context(session_factory())
        if method == "hybrid" and ft_session is not session:
            (qv, vec), (tsq, kw) = await _both(vector_branch(), fulltext_branch(ft_session))
        else:
            if method in ("vector", "hybrid"):
                qv, vec = await vector_branch()
            if method in ("full_text", "hybrid"):
                tsq, kw = await fulltext_branch(session)

        if method == "vector":
            scores = vec
        elif method == "full_text":
            scores = kw
        elif use_rerank:  # 混合-Rerank：两路候选取并集，得分由重排给出
            scores = dict.fromkeys(vec.keys() | kw.keys(), 0.0)
        else:  # 混合-权重（含 Rerank 不可用时的退化）：并集内缺失的另一路得分按 ID 补算（两路并发）
            weight = config.vector_weight if config.hybrid_mode == "weighted" else SKIPPED_HYBRID_WEIGHT
            ids = vec.keys() | kw.keys()
            miss_v = [i for i in ids if i not in vec]
            miss_k = [i for i in ids if i not in kw]

            async def extra_kw() -> dict[int, float]:
                return await fulltext_scores_by_ids(ft_session, dataset_id, table, tsq, miss_k) if tsq else {}

            if ft_session is not session:
                extra_v, extra_k = await _both(store.score_by_ids(dataset_id, table, qv, miss_v), extra_kw())
            else:
                extra_v = await store.score_by_ids(dataset_id, table, qv, miss_v)
                extra_k = await extra_kw()
            vec.update(extra_v)
            kw.update(extra_k)
            scores = {i: weight * vec.get(i, 0.0) + (1 - weight) * kw.get(i, 0.0) for i in ids}

    units_map = await retrieval_repo.load_units(session, dataset_id, table, list(scores))
    scores = {i: sc for i, sc in scores.items() if i in units_map}

    if use_rerank and scores and reranker is not None:
        order = sorted(scores)
        rescored = await reranker(query, [units_map[i].content for i in order])
        scores = dict(zip(order, rescored, strict=True))

    if config.score_threshold_enabled:
        scores = {i: sc for i, sc in scores.items() if sc >= config.score_threshold}

    records = (
        await _aggregate_parent(session, dataset_id, scores, units_map, config.top_k)
        if parent_child
        else await _top_general(session, dataset_id, scores, config.top_k)
    )
    return RetrievalOutcome(records, skipped, RERANK_SKIPPED_REASON if skipped else None)


def _ranked(scores: dict[int, float]) -> list[tuple[int, float]]:
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


async def _top_general(
    session: AsyncSession, dataset_id: int, scores: dict[int, float], top_k: int
) -> list[RecallRecord]:
    ranked = _ranked(scores)[:top_k]
    segs = await retrieval_repo.load_segments(session, dataset_id, [i for i, _ in ranked])
    return [_record(segs[i], score, []) for i, score in ranked if i in segs]


async def _aggregate_parent(
    session: AsyncSession, dataset_id: int, scores: dict[int, float], units: dict[int, UnitRow], top_k: int
) -> list[RecallRecord]:
    """按父块分组：父块得分 = 命中子块最高分；子块按得分降序附带；Top K 按父块计。"""
    groups: dict[int, list[tuple[int, float]]] = {}
    for child_id, score in _ranked(scores):
        parent_id = units[child_id].parent_id
        if parent_id is not None:
            groups.setdefault(parent_id, []).append((child_id, score))
    # 子块已按得分降序加入，组内首个即最高分
    ranked_parents = sorted(groups.items(), key=lambda kv: (-kv[1][0][1], kv[0]))[:top_k]
    segs = await retrieval_repo.load_segments(session, dataset_id, [p for p, _ in ranked_parents])
    out: list[RecallRecord] = []
    for parent_id, hits in ranked_parents:
        if parent_id not in segs:
            continue
        children = [
            RecallChildChunk(id=cid, position=units[cid].position, content=units[cid].content, score=round(s, 4))
            for cid, s in hits
        ]
        out.append(_record(segs[parent_id], hits[0][1], children))
    return out


def _record(seg: retrieval_repo.SegmentRow, score: float, children: list[RecallChildChunk]) -> RecallRecord:
    return RecallRecord(
        segment_id=seg.id,
        position=seg.position,
        segment_type=seg.segment_type,  # type: ignore[arg-type]
        content=seg.content,
        score=round(score, 4),
        keywords=seg.keywords,
        document=RecallDocument(id=seg.document_id, name=seg.document_name),
        child_chunks=children,
    )
