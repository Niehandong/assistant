"""全文检索支撑：jieba 分词 + tsvector 表达式（索引侧）与 tsquery 查询（BE-21）。

索引文本经 ``jieba.cut_for_search`` 分词、空格连接后交给 ``to_tsvector('simple', ...)``；
通用分段：关键词权重 A、内容权重 B；子块：内容权重 B。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Sequence
from typing import Any

import jieba  # type: ignore[import-untyped]
from sqlalchemy import Text, bindparam, func, literal_column, select
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import Settings, get_settings
from app.core.constants import TASK_STREAM
from app.engine.vector_store import UnitTable, bump_metric, unit_model
from platform_common.events.publisher import publish
from platform_common.redis import get_redis

logger = logging.getLogger(__name__)

_init_lock = threading.Lock()
_initialized = False


def _ensure_jieba() -> None:
    """惰性初始化（首次加载词典约 1 秒；线程安全）。调用方在线程中执行分词。"""
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        jieba.setLogLevel(logging.WARNING)
        user_dict = get_settings().JIEBA_USER_DICT
        if user_dict:
            jieba.load_userdict(user_dict)
        jieba.initialize()
        _initialized = True


def tokenize(text: str) -> str:
    """搜索引擎模式分词，空格连接；空白词丢弃。"""
    _ensure_jieba()
    return " ".join(w for w in jieba.cut_for_search(text) if w.strip())


def tokenize_keywords(keywords: Sequence[str]) -> str:
    """关键词不再切分，按整词保留（同时保留其分词结果便于命中）。"""
    return " ".join(t for k in keywords if k.strip() for t in (k.strip(), tokenize(k)))


def tsv_expr(
    tokens: ColumnElement[Any] | str, keyword_tokens: ColumnElement[Any] | str | None = None
) -> ColumnElement[Any]:
    """tsvector 表达式：内容权重 B，可选关键词权重 A。入参为已分词文本（字符串或绑定参数）。"""
    simple: ColumnElement[Any] = literal_column("'simple'")
    content = func.setweight(func.to_tsvector(simple, tokens, type_=TSVECTOR), literal_column("'B'"), type_=TSVECTOR)
    if keyword_tokens is None:
        return content
    kw = func.setweight(func.to_tsvector(simple, keyword_tokens, type_=TSVECTOR), literal_column("'A'"), type_=TSVECTOR)
    return kw.op("||", return_type=TSVECTOR)(content)


def tokens_param(name: str = "b_tokens") -> ColumnElement[Any]:
    return bindparam(name, type_=Text)


# ---------------------------------------------------------------- 查询侧（BE-21）

MAX_QUERY_TERMS = 50

# 查询侧停用词：高频虚词/疑问词会让 OR 查询命中大半个知识库，对 ts_rank_cd 的排序开销影响极大（BE-21 压测）。
# 仅用于查询；索引侧保持不变。过滤后若一个词都不剩，则回退为不过滤。
STOPWORDS: frozenset[str] = frozenset(
    "的 了 是 在 有 和 就 都 而 及 与 着 或 一 个 没 不 也 很 到 说 要 去 你 我 他 她 它 们 "
    "这 那 之 为 以 其 把 被 让 给 对 从 向 "
    "吗 呢 吧 啊 么 呀 哦 嘛 哪 啥 什么 怎么 怎样 如何 哪些 哪个 是否 可以 能否 请问 请 能 会 "
    "the a an of to is are was were be in on at for and or with by as it this that".split()
)


def _has_word_char(token: str) -> bool:
    return any(ch.isalnum() for ch in token)


def build_terms(query: str) -> list[str]:
    """查询文本 → 去重后的查询词列表（保序）。

    jieba 搜索引擎模式分词，去掉空白与纯标点、去重；去掉反斜杠；
    默认再去掉查询侧停用词（``FULLTEXT_DROP_STOPWORDS``，过滤后为空则回退不过滤）；最多 ``MAX_QUERY_TERMS`` 个。
    """
    seen: dict[str, None] = {}
    for tok in tokenize(query).split():
        tok = tok.replace("\\", "").strip()
        if tok and _has_word_char(tok):
            seen.setdefault(tok)
    if not seen:
        return []
    if get_settings().FULLTEXT_DROP_STOPWORDS:
        kept = {t: None for t in seen if t.lower() not in STOPWORDS}
        seen = kept or seen
    return list(seen)[:MAX_QUERY_TERMS]


def terms_to_tsquery(terms: Sequence[str], op: str = "|") -> str:
    """词列表 → tsquery 字符串：词内单引号转义为 ``''``，每词加单引号作为字面词素，词间以 ``op``（``|`` / ``&``）连接。

    结果只作为**绑定参数**传给 ``to_tsquery('simple', :q)``。
    """
    return f" {op} ".join("'" + t.replace("'", "''") + "'" for t in terms)


def build_tsquery(query: str) -> str | None:
    """查询文本 → tsquery 字符串（词间 OR）；无有效词返回 None。"""
    terms = build_terms(query)
    return terms_to_tsquery(terms) if terms else None


def _tsquery(tsq: str, name: str = "tsq") -> ColumnElement[Any]:
    return func.to_tsquery(literal_column("'simple'"), bindparam(name, tsq, type_=Text))


async def fulltext_search(
    session: AsyncSession, dataset_id: int, table: UnitTable, tsq: str, limit: int
) -> list[tuple[int, float]]:
    """``tsv @@ q``，``ts_rank_cd(tsv, q, 32)``（已归一化到 0~1）降序，同分 ID 升序。

    注意 ``where(t.search_enabled)``：必须渲染成裸布尔列，才能命中部分索引（``IS true`` 无法被规划器证明蕴含索引谓词）。
    """
    t = unit_model(table)
    q = _tsquery(tsq)
    rank = func.ts_rank_cd(t.tsv, q, 32)
    stmt = (
        select(t.id, rank.label("rank"))
        .where(t.dataset_id == dataset_id, t.search_enabled, t.tsv.op("@@")(q))
        .order_by(rank.desc(), t.id)
        .limit(limit)
    )
    return [(int(r[0]), float(r[1])) for r in (await session.execute(stmt)).all()]


async def fulltext_scores_by_ids(
    session: AsyncSession, dataset_id: int, table: UnitTable, tsq: str, ids: Sequence[int]
) -> dict[int, float]:
    """对指定 ID 计算关键词得分（不匹配为 0）；不可检索的 ID 不在结果中。"""
    if not ids:
        return {}
    t = unit_model(table)
    q = _tsquery(tsq)
    stmt = select(t.id, func.ts_rank_cd(t.tsv, q, 32)).where(
        t.dataset_id == dataset_id, t.search_enabled, t.id.in_(list(ids))
    )
    return {int(r[0]): float(r[1]) for r in (await session.execute(stmt)).all()}


async def build_tsquery_async(query: str) -> str | None:
    """jieba 首次初始化约 1 秒，放到线程里避免阻塞事件循环。"""
    return await asyncio.to_thread(build_tsquery, query)


async def build_terms_async(query: str) -> list[str]:
    return await asyncio.to_thread(build_terms, query)


# ---------------------------------------------------------------- 大库候选裁剪（BE-21b，tech-design-m2 3.10.4）

METRIC_FTS_CAP_HIT = "kb:metrics:fts_cap_hit"
COMMON_TERMS_KEY = "kb:fts:common:{dataset_id}"  # Redis 哈希：词 → 文档频率；空字段 "" 为"已计算"哨兵
COMMON_TERMS_REQ_KEY = "kb:fts:common:req:{dataset_id}"  # 触发任务的去重标记（5 分钟）
COMMON_TERMS_SENTINEL = ""
TASK_FTS_COMMON_TERMS = "fts.common_terms"


def common_terms_key(dataset_id: int) -> str:
    return COMMON_TERMS_KEY.format(dataset_id=int(dataset_id))


async def load_common_terms(dataset_id: int) -> dict[str, int] | None:
    """读取知识库的常见词表（词 → 文档频率）；缺失或 Redis 不可用返回 None。"""
    try:
        data = await get_redis().hgetall(common_terms_key(dataset_id))
    except Exception:
        logger.warning("读取常见词表失败，按未裁剪的兜底处理", exc_info=True)
        return None
    if not data:
        return None
    return {str(k): int(v) for k, v in data.items() if k != COMMON_TERMS_SENTINEL}


async def request_common_terms(dataset_id: int) -> None:
    """词表缺失时让 kb-worker 异步计算（5 分钟内去重）；失败只记日志。"""
    try:
        r = get_redis()
        if await r.set(COMMON_TERMS_REQ_KEY.format(dataset_id=int(dataset_id)), "1", nx=True, ex=300):
            await publish(TASK_STREAM, TASK_FTS_COMMON_TERMS, {"dataset_id": int(dataset_id)})
    except Exception:
        logger.warning("触发常见词表计算失败", exc_info=True)


async def _ranked_candidates(
    session: AsyncSession, t: Any, dataset_id: int, cand_q: str, full_q: str, cap: int, limit: int
) -> tuple[list[tuple[int, float]], int]:
    """候选 = 命中 ``cand_q`` 的行（最多 cap，无序截断）；只对候选用完整查询 ``full_q`` 打分取前 limit。

    返回 (结果, 候选行数)；``count() OVER ()`` 在 ORDER BY/LIMIT 之前求值，等于候选总数。
    """
    cq = _tsquery(cand_q, "cq")
    fq = _tsquery(full_q, "fq")
    cand = (
        select(t.id.label("id"), t.tsv.label("tsv"))
        .where(t.dataset_id == dataset_id, t.search_enabled, t.tsv.op("@@")(cq))
        .limit(cap)
        .subquery("cand")
    )
    rank = func.ts_rank_cd(cand.c.tsv, fq, 32)
    stmt = (
        select(cand.c.id, rank.label("rank"), func.count().over().label("n"))
        .order_by(rank.desc(), cand.c.id)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(int(r[0]), float(r[1])) for r in rows], (int(rows[0][2]) if rows else 0)


async def fulltext_search_pruned(
    session: AsyncSession,
    dataset_id: int,
    table: UnitTable,
    terms: Sequence[str],
    limit: int,
    *,
    common: dict[str, int] | None,
    settings: Settings | None = None,
) -> list[tuple[int, float]]:
    """大库全文检索：按常见词裁剪候选，再用完整查询（全部词 OR）打分。

    * ``common`` 缺失（None）：完整 OR 查询 + 候选上限兜底；
    * 有稀有词：候选 = 命中任一稀有词的行；
    * 全是常见词：候选 = 命中全部常见词（AND）的行，为空则退化为命中"最稀有的常见词"的行。
    得分数值与未裁剪时相同（同一个 ``ts_rank_cd``）。
    """
    s = settings or get_settings()
    t = unit_model(table)
    cap = s.FULLTEXT_CANDIDATE_CAP
    full_q = terms_to_tsquery(terms)
    if common is None:
        plans = [full_q]
    else:
        rare = [w for w in terms if w.lower() not in common]
        if rare:
            plans = [terms_to_tsquery(rare)]
        else:
            rarest = min(terms, key=lambda w: common.get(w.lower(), 0))
            plans = [terms_to_tsquery(terms, "&"), terms_to_tsquery([rarest])]
    result: list[tuple[int, float]] = []
    for cand_q in plans:
        result, n_cand = await _ranked_candidates(session, t, dataset_id, cand_q, full_q, cap, limit)
        if n_cand >= cap:
            await bump_metric(METRIC_FTS_CAP_HIT)
        if result:
            break
    return result
