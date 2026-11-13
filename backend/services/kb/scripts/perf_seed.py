# ruff: noqa: E501
"""检索性能压测：造数据 / 建索引 / 测延迟 / 召回率 / 全文裁剪重合度 / EXPLAIN / 写入开销 / 清理（BE-21、BE-21b）。

只允许在名称含 ``test`` 的库上运行（默认 kbp_test、Redis db1），避免污染开发库。

    cd backend/services/kb
    P=../../../.venv/bin/python
    $P scripts/perf_seed.py seed --scenario s2          # s1：通用 + 父子各 10 万（随机向量）；s2：在 s1 上加 4 个聚类大库 + 20 个小库 + 768 维模型的大库
    $P scripts/perf_seed.py writebench --label noindex  # 建索引前：索引阶段写入 1 万单元耗时
    $P scripts/perf_seed.py index                       # 经 kb-worker 的对账逻辑建 HNSW 索引（记录耗时与大小）
    $P scripts/perf_seed.py fts                         # 计算大库常见词表
    $P scripts/perf_seed.py explain | bench | recall | overlap | writebench --label withindex
    $P scripts/perf_seed.py clean

数据：1024 维向量（服务端生成）+ 以 jieba 词典词频随机抽词拼成的中文文本。向量有两种：``random``（均匀随机，HNSW 最坏情况）与
``clustered``（200 个随机中心 + 噪声，查询向量取库内已有向量加小噪声，更接近真实分布）。
bench 直接调用检索引擎 ``retrieve``，查询向量预置，所以**不含**向量/重排模型调用耗时；包含 jieba 分词、全部 SQL、结果组装。
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import os
import random
import re
import statistics
import sys
import time
from collections.abc import Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

KB_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KB_DIR))

DEFAULT_URL = "postgresql+asyncpg://kbp:kbp@localhost:15432/kbp_test"
os.environ.setdefault("DATABASE_URL", DEFAULT_URL)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("REDIS_URL", "redis://localhost:16379/1")

import jieba  # type: ignore[import-untyped]  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.engine import vector_store  # noqa: E402
from app.engine.fulltext import (  # noqa: E402
    build_terms,
    fulltext_search,
    fulltext_search_pruned,
    load_common_terms,
    terms_to_tsquery,
)
from app.engine.retriever import retrieve  # noqa: E402
from app.engine.vector_store import PgVectorStore, valid_indexes  # noqa: E402
from app.schemas.dataset import RetrievalConfig  # noqa: E402
from app.worker import fts_stats, vector_index  # noqa: E402
from platform_common.db import dispose_db, get_engine, get_session_factory, init_db  # noqa: E402
from platform_common.redis import close_redis, get_redis, init_redis  # noqa: E402

PERF_OWNER = 987654321
DIM = 1024
DOC_COUNT = 200
NOISE_AMP = 0.8  # 聚类向量：中心（每维 U(-.5,.5)）+ 三角分布噪声（幅度）
QUERY_NOISE_SD = 0.05  # 聚类库查询向量 = 库内向量 + N(0, sd)
BIG = 20000  # 与 VECTOR_EXACT_MAX_ROWS 一致：超过算大库
BATCH = 1000


def make_settings() -> Settings:
    s = Settings()
    if "test" not in s.DATABASE_URL.rsplit("/", 1)[-1]:
        sys.exit(f"拒绝运行：数据库名必须包含 test（当前 {s.DATABASE_URL.rsplit('/', 1)[-1]}）")
    return s


# ---------------------------------------------------------------- 文本

_vocab: tuple[list[str], list[int]] | None = None


def vocabulary() -> tuple[list[str], list[int]]:
    """jieba 词典中 1~4 字的纯汉字词与累计词频（真实 Zipf 分布）。"""
    global _vocab
    if _vocab is None:
        jieba.setLogLevel(60)
        jieba.initialize()
        words = [w for w, f in jieba.dt.FREQ.items() if f and 1 <= len(w) <= 4 and all("一" <= c <= "鿿" for c in w)]
        freqs = [jieba.dt.FREQ[w] for w in words]
        _vocab = (words, list(itertools.accumulate(freqs)))
    return _vocab


def gen_words(rng: random.Random, n_words: int) -> list[str]:
    words, cum = vocabulary()
    return rng.choices(words, cum_weights=cum, k=n_words)


# ---------------------------------------------------------------- 造数据

RANDOM_VEC_SQL = "CAST(CAST((SELECT array_agg(random()::real - 0.5) FROM generate_series(1, CAST(:dim AS int) + u.i * 0)) AS vector) AS halfvec)"
# 聚类向量：center[cid] + 三角噪声；cid = 1 + (序号 % 200)
CLUSTER_VEC_SQL = (
    "CAST(CAST((SELECT array_agg(cv.v[g] + CAST(:amp AS float8) * (random() + random() - 1.0) ORDER BY g) "
    "FROM generate_series(1, CAST(:dim AS int)) g, public.{centers} cv WHERE cv.cid = 1 + (u.i % 200)) AS vector) AS halfvec)"
)


async def _scalar(sql: str, **p: object) -> int:
    async with get_session_factory()() as s:
        return int((await s.execute(text(sql), p)).scalar_one())


async def _create_dataset(name: str, chunk_mode: str, docs: int, model_id: int) -> tuple[int, list[int]]:
    async with get_session_factory()() as s:
        ds = (
            await s.execute(
                text(
                    "INSERT INTO kb.dataset (name, owner_id, company_id, dept_id, embedding_model_id, chunk_mode, "
                    "available_doc_count, doc_count, created_by, updated_by) "
                    "VALUES (:n, :o, 1, 1, :m, :c, :d, :d, :o, :o) RETURNING id"
                ),
                {"n": name, "o": PERF_OWNER, "m": model_id, "c": chunk_mode, "d": docs},
            )
        ).scalar_one()
        base = 90_000_000 + int(ds) * 1000
        rows = (
            (
                await s.execute(
                    text(
                        "INSERT INTO kb.document (dataset_id, upload_file_id, name, file_ext, file_size, file_hash, "
                        "storage_key, chunk_mode, process_rule, status, created_by, updated_by) "
                        "SELECT CAST(:ds AS bigint), CAST(:base AS bigint) + g, '压测文档' || g || '.txt', 'txt', 1000, "
                        "lpad(CAST(CAST(:ds AS bigint) AS text) || '_' || CAST(g AS text), 64, '0'), 'perf/' || g, :c, '{}'::jsonb, 'available', :o, :o "
                        "FROM generate_series(1, :docs) g RETURNING id"
                    ),
                    {"ds": ds, "base": base, "c": chunk_mode, "o": PERF_OWNER, "docs": docs},
                )
            )
            .scalars()
            .all()
        )
        await s.commit()
    return int(ds), [int(r) for r in rows]


async def _insert_batch(sql: str, params: dict[str, object]) -> None:
    async with get_session_factory()() as s:
        await s.execute(text(sql), params)
        await s.commit()


SEG_SQL = (
    "INSERT INTO kb.segment (dataset_id, document_id, position, segment_type, content, char_count, token_count, "
    "index_status, embedding, embedding_model_id, tsv, search_enabled, created_by, updated_by) "
    "SELECT :ds, (CAST(:docs AS bigint[]))[1 + (u.i % :nd)], u.i, :stype, u.c, length(u.c), length(u.c), :ist, "
    "{vec}, :mid, {tsv}, true, :o, :o "
    "FROM unnest(CAST(:contents AS text[]), CAST(:tokens AS text[]), CAST(:idx AS int[])) AS u(c, t, i)"
)
SEG_PLAIN_SQL = (
    "INSERT INTO kb.segment (dataset_id, document_id, position, segment_type, content, char_count, token_count, "
    "index_status, search_enabled, created_by, updated_by) "
    "SELECT :ds, (CAST(:docs AS bigint[]))[1 + (u.i % :nd)], u.i, 'parent', u.c, length(u.c), length(u.c), 'indexed', false, :o, :o "
    "FROM unnest(CAST(:contents AS text[]), CAST(:idx AS int[])) AS u(c, i) RETURNING id"
)
CHILD_SQL = (
    "INSERT INTO kb.child_chunk (dataset_id, document_id, segment_id, generation, position, content, char_count, "
    "token_count, index_status, embedding, embedding_model_id, tsv, search_enabled, created_by, updated_by) "
    "SELECT :ds, (CAST(:docs AS bigint[]))[1 + (u.i % :nd)], (CAST(:parents AS bigint[]))[1 + (u.i % :np)], 1, u.i, u.c, length(u.c), length(u.c), "
    "'indexed', {vec}, :mid, {tsv}, true, :o, :o "
    "FROM unnest(CAST(:contents AS text[]), CAST(:tokens AS text[]), CAST(:idx AS int[])) AS u(c, t, i)"
)
TSV = "setweight(to_tsvector('simple', u.t), 'B')"


def vec_sql(kind: str, dim: int) -> str:
    return RANDOM_VEC_SQL if kind == "random" else CLUSTER_VEC_SQL.format(centers=f"perf_center_{dim}")


async def seed_general(
    name: str, units: int, model_id: int, dim: int, kind: str, rng: random.Random, docs: int = DOC_COUNT
) -> int:
    ds, doc_ids = await _create_dataset(name, "general", docs, model_id)
    sql = SEG_SQL.format(vec=vec_sql(kind, dim), tsv=TSV).replace(":stype", "'general'").replace(":ist", "'indexed'")
    t0 = time.perf_counter()
    for start in range(0, units, BATCH):
        n = min(BATCH, units - start)
        word_lists = [gen_words(rng, 120) for _ in range(n)]
        params: dict[str, object] = {
            "ds": ds, "docs": doc_ids, "nd": len(doc_ids), "o": PERF_OWNER, "dim": dim, "mid": model_id,
            "contents": ["".join(w) for w in word_lists], "tokens": [" ".join(w) for w in word_lists],
            "idx": list(range(start, start + n)),
        }  # fmt: skip
        if kind == "clustered":
            params["amp"] = NOISE_AMP
        await _insert_batch(sql, params)
        if units >= 10000 and (start // BATCH) % 20 == 0:
            print(f"  {name} {start + n}/{units}  {time.perf_counter() - t0:.0f}s", flush=True)
    await _insert_batch("UPDATE kb.dataset SET segment_count = :n WHERE id = :d", {"n": units, "d": ds})
    return ds


async def seed_parent_child(
    name: str, units: int, model_id: int, dim: int, kind: str, rng: random.Random, docs: int = DOC_COUNT
) -> int:
    ds, doc_ids = await _create_dataset(name, "parent_child", docs, model_id)
    parents_n = max(1, units // 4)
    parents: list[int] = []
    for start in range(0, parents_n, BATCH):
        n = min(BATCH, parents_n - start)
        contents = ["".join(gen_words(rng, 240)) for _ in range(n)]
        async with get_session_factory()() as s:
            ids = (
                await s.execute(
                    text(SEG_PLAIN_SQL),
                    {"ds": ds, "docs": doc_ids, "nd": len(doc_ids), "o": PERF_OWNER, "contents": contents,
                     "idx": list(range(start, start + n))},
                )
            ).scalars().all()  # fmt: skip
            await s.commit()
        parents.extend(int(i) for i in ids)
    sql = CHILD_SQL.format(vec=vec_sql(kind, dim), tsv=TSV)
    t0 = time.perf_counter()
    for start in range(0, units, BATCH):
        n = min(BATCH, units - start)
        word_lists = [gen_words(rng, 60) for _ in range(n)]
        params: dict[str, object] = {
            "ds": ds, "docs": doc_ids, "nd": len(doc_ids), "parents": parents, "np": len(parents), "o": PERF_OWNER,
            "dim": dim, "mid": model_id, "contents": ["".join(w) for w in word_lists],
            "tokens": [" ".join(w) for w in word_lists], "idx": list(range(start, start + n)),
        }  # fmt: skip
        if kind == "clustered":
            params["amp"] = NOISE_AMP
        await _insert_batch(sql, params)
        if units >= 10000 and (start // BATCH) % 20 == 0:
            print(f"  {name} {start + n}/{units}  {time.perf_counter() - t0:.0f}s", flush=True)
    await _insert_batch(
        "UPDATE kb.dataset SET segment_count = :p, child_segment_count = :n WHERE id = :d",
        {"p": len(parents), "n": units, "d": ds},
    )
    return ds


async def create_centers(dim: int, rng: random.Random) -> None:
    table = f"public.perf_center_{dim}"
    async with get_session_factory()() as s:
        await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
        await s.execute(text(f"CREATE TABLE {table} (cid int PRIMARY KEY, v real[] NOT NULL)"))
        for cid in range(1, 201):
            await s.execute(
                text(f"INSERT INTO {table} VALUES (:c, CAST(:v AS real[]))"),
                {"c": cid, "v": [rng.uniform(-0.5, 0.5) for _ in range(dim)]},
            )
        await s.commit()


async def create_models() -> dict[int, int]:
    """压测用 Embedding 模型（kb.ai_model），索引对账据此建索引；返回 {维度: 模型 ID}。"""
    out: dict[int, int] = {}
    async with get_session_factory()() as s:
        for dim in (1024, 768):
            out[dim] = int(
                (
                    await s.execute(
                        text(
                            "INSERT INTO kb.ai_model (name, model_type, base_url, model_name, dimension, status, created_by, updated_by) "
                            "VALUES (:n, 'embedding', 'http://perf.invalid/v1', 'perf', :d, 'enabled', :o, :o) RETURNING id"
                        ),
                        {"n": f"perf-emb-{dim}", "d": dim, "o": PERF_OWNER},
                    )
                ).scalar_one()
            )
        await s.commit()
    return out


async def analyze() -> None:
    async with get_engine().connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        for t in ("kb.segment", "kb.child_chunk", "kb.document", "kb.dataset"):
            await conn.execute(text(f"ANALYZE {t}"))


async def cmd_seed(scenario: str, units: int, seed: int) -> None:
    async with get_session_factory()() as s:
        if (
            await s.execute(text("SELECT count(*) FROM kb.dataset WHERE owner_id = :o"), {"o": PERF_OWNER})
        ).scalar_one():
            sys.exit("已存在压测数据，请先执行 clean")
    nrng = random.Random(seed)
    models = await create_models()
    m1, m2 = models[1024], models[768]
    await create_centers(1024, nrng)
    t0 = time.perf_counter()
    info: dict[str, int] = {}
    print(f"造数据 {scenario}：主模型 {m1}（1024 维）、副模型 {m2}（768 维）")
    jobs = [
        ("s1_general_random", seed_general("perf-s1-general-random", units, m1, 1024, "random", random.Random(seed))),
        ("s1_pc_random", seed_parent_child("perf-s1-pc-random", units, m1, 1024, "random", random.Random(seed + 100))),
    ]
    small: list[Coroutine[Any, Any, int]] = []
    if scenario == "s2":
        await create_centers(768, nrng)
        for k, (name, mode, mid, dim) in enumerate(
            [
                ("big1_general_clustered", "general", m1, 1024),
                ("big2_pc_clustered", "parent_child", m1, 1024),
                ("big3_general_clustered", "general", m1, 1024),
                ("big4_pc_clustered", "parent_child", m1, 1024),
                ("m2_general_clustered", "general", m2, 768),
            ]
        ):
            fn = seed_general if mode == "general" else seed_parent_child
            jobs.append(
                (name, fn(f"perf-{name.replace('_', '-')}", units, mid, dim, "clustered", random.Random(seed + 1 + k)))
            )
        for i in range(10):
            small.append(
                seed_general(
                    f"perf-small-g{i}-clustered", 2000, m1, 1024, "clustered", random.Random(seed + 10 + i), docs=20
                )
            )
            small.append(
                seed_parent_child(
                    f"perf-small-p{i}-clustered", 2000, m1, 1024, "clustered", random.Random(seed + 30 + i), docs=20
                )
            )

    async def run_small() -> None:
        for c in small:
            await c

    ids = await asyncio.gather(*(c for _, c in jobs), run_small())  # 各库并发写入（服务端并行生成向量）
    info.update({name: ids[i] for i, (name, _) in enumerate(jobs)})
    await analyze()
    sizes = await _scalar("SELECT pg_total_relation_size('kb.segment') + pg_total_relation_size('kb.child_chunk')")
    info["elapsed_s"] = round(time.perf_counter() - t0)
    info["segment_plus_child_table_mb"] = sizes // 1024 // 1024
    info["models"] = models  # type: ignore[assignment]
    print(json.dumps(info, ensure_ascii=False))


async def cmd_clean() -> None:
    async with get_session_factory()() as s:
        ids = [
            r[0]
            for r in (await s.execute(text("SELECT id FROM kb.dataset WHERE owner_id = :o"), {"o": PERF_OWNER})).all()
        ]
        for t in ("kb.child_chunk", "kb.segment", "kb.document"):
            await s.execute(text(f"DELETE FROM {t} WHERE dataset_id = ANY(:ids)"), {"ids": ids})
        await s.execute(text("DELETE FROM kb.dataset WHERE id = ANY(:ids)"), {"ids": ids})
        await s.execute(text("DELETE FROM kb.ai_model WHERE created_by = :o"), {"o": PERF_OWNER})
        for dim in (1024, 768):
            await s.execute(text(f"DROP TABLE IF EXISTS public.perf_center_{dim}"))
        await s.commit()
    await vector_index.reconcile(None)  # 没有活跃模型：删除全部 HNSW 索引
    r = get_redis()
    for did in ids:
        await r.delete(fts_stats.common_terms_key(did), fts_stats._ts_key(did), f"kb:fts:common:req:{did}")
    for k in (vector_store.METRIC_HNSW_FALLBACK, "kb:metrics:fts_cap_hit"):
        await r.delete(k)
    async with get_engine().connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        for t in ("kb.child_chunk", "kb.segment", "kb.document", "kb.dataset", "kb.ai_model"):
            await conn.execute(text(f"VACUUM {t}"))
    print(f"已清理 {len(ids)} 个压测知识库及其数据、压测模型、HNSW 索引、辅助表")


# ---------------------------------------------------------------- 公共：库清单、查询、向量

NATURAL_QUERIES = [
    "员工年假有几天",
    "报销流程需要哪些审批",
    "公司差旅费用标准是什么",
    "服务器故障应急预案怎么处理",
    "合同签订前的法务审核要求",
    "新员工入职需要准备哪些材料",
    "项目验收的标准和流程",
    "信息安全管理制度",
]
COMMON_QUERY = "公司的员工是我们的"  # 全是高频词：全文检索最坏情况


@dataclass
class Lib:
    id: int
    name: str
    mode: str
    model_id: int
    dim: int
    units: int
    kind: str  # random | clustered

    @property
    def table(self) -> str:
        return "child_chunk" if self.mode == "parent_child" else "segment"

    @property
    def big(self) -> bool:
        return self.units > BIG


async def load_libs() -> list[Lib]:
    async with get_session_factory()() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT d.id, d.name, d.chunk_mode, d.embedding_model_id, m.dimension, "
                    "CASE WHEN d.chunk_mode = 'parent_child' THEN d.child_segment_count ELSE d.segment_count END "
                    "FROM kb.dataset d JOIN kb.ai_model m ON m.id = d.embedding_model_id WHERE d.owner_id = :o ORDER BY d.id"
                ),
                {"o": PERF_OWNER},
            )
        ).all()
    if not rows:
        sys.exit("没有压测数据，请先执行 seed")
    return [
        Lib(r[0], r[1], r[2], r[3], r[4], r[5], "random" if name_kind(r[1]) == "random" else "clustered") for r in rows
    ]


def name_kind(name: str) -> str:
    return "random" if name.endswith("-random") else "clustered"


def make_queries(seed: int) -> list[str]:
    rng = random.Random(seed + 1)
    mid = [w for w in gen_words(rng, 4000) if len(w) >= 2]
    return [*NATURAL_QUERIES, *("".join(rng.sample(mid, 4)) for _ in range(8)), COMMON_QUERY]


async def sample_vectors(lib: Lib, n: int, rng: random.Random) -> list[list[float]]:
    """随机库：均匀随机向量；聚类库：库内随机已有向量 + 小噪声。"""
    if lib.kind == "random":
        return [[rng.random() - 0.5 for _ in range(lib.dim)] for _ in range(n)]
    if not lib.big:  # 小库：取库内前 n 条（min/max 在小库上会沿主键索引长时间扫描）
        async with get_session_factory()() as s:
            raws = (
                await s.execute(
                    text(
                        f"SELECT CAST(embedding AS text) FROM kb.{lib.table} "
                        "WHERE dataset_id = :d AND search_enabled ORDER BY id LIMIT :n"
                    ),
                    {"d": lib.id, "n": n},
                )
            ).scalars().all()  # fmt: skip
        return [[float(x) + rng.gauss(0, QUERY_NOISE_SD) for x in json.loads(r)] for r in raws]
    async with get_session_factory()() as s:
        lo, hi = (
            await s.execute(
                text(f"SELECT min(id), max(id) FROM kb.{lib.table} WHERE dataset_id = :d AND search_enabled"),
                {"d": lib.id},
            )
        ).one()
        out: list[list[float]] = []
        for _ in range(n):
            pivot = rng.randint(int(lo), int(hi))
            raw = (
                await s.execute(
                    text(
                        f"SELECT CAST(embedding AS text) FROM kb.{lib.table} "
                        "WHERE dataset_id = :d AND search_enabled AND id >= :p ORDER BY id LIMIT 1"
                    ),
                    {"d": lib.id, "p": pivot},
                )
            ).scalar_one()
            out.append([float(x) + rng.gauss(0, QUERY_NOISE_SD) for x in json.loads(raw)])
    return out


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def stats(lat: list[float]) -> dict[str, float]:
    return {
        "n": len(lat),
        "p50_ms": round(statistics.median(lat), 1),
        "p95_ms": round(pct(lat, 95), 1),
        "max_ms": round(max(lat), 1),
    }


# ---------------------------------------------------------------- 压测

HNSW_CALLS = {"n": 0}


def count_hnsw_calls() -> None:
    orig = PgVectorStore.search_hnsw

    async def wrapped(self: PgVectorStore, *a: object, **k: object) -> object:
        HNSW_CALLS["n"] += 1
        return await orig(self, *a, **k)  # type: ignore[arg-type]

    PgVectorStore.search_hnsw = wrapped  # type: ignore[method-assign]


async def bench_one(
    lib: Lib, config: RetrievalConfig, queries: list[str], vectors: list[list[float]], samples: int, concurrency: int
) -> list[float]:
    cfg_queries = list(zip(queries, vectors, strict=True))
    lat: list[float] = []
    factory = get_session_factory()

    async def one(i: int, record: bool = True) -> None:
        q, v = cfg_queries[i % len(cfg_queries)]

        async def embed(_: str) -> list[float]:
            return v

        async with factory() as s:
            t = time.perf_counter()
            out = await retrieve(
                s, dataset_id=lib.id, chunk_mode=lib.mode, query=q, config=config, embed_query=embed,
                embedding_model_id=lib.model_id, dimension=lib.dim, units=lib.units, session_factory=factory,
            )  # fmt: skip
            if record:
                lat.append((time.perf_counter() - t) * 1000)
            assert out.records is not None

    for i in range(
        len(cfg_queries)
    ):  # 预热：每条查询先完整执行一遍（索引/堆页读入缓存；本机为机械盘，冷读每页约 12ms）
        await one(i, record=False)
    sem = asyncio.Semaphore(concurrency)

    async def guarded(i: int) -> None:
        async with sem:
            await one(i)

    await asyncio.gather(*(guarded(i) for i in range(samples)))
    return lat


async def cmd_bench(samples: int, concurrency: int, top_k: int, seed: int, only: str = "all") -> None:
    libs = [lib for lib in await load_libs() if only == "all" or (only == "big") == lib.big]
    count_hnsw_calls()
    queries = make_queries(seed)
    nrng = random.Random(seed + 7)
    result: dict[str, dict[str, dict[str, float]]] = {}
    pooled: dict[tuple[str, str], list[float]] = {}
    for lib in libs:
        vectors = await sample_vectors(lib, len(queries), nrng)
        for method in ("vector", "full_text", "hybrid"):
            cfg = RetrievalConfig(search_method=method, top_k=top_k)
            if lib.big:
                lat = await bench_one(lib, cfg, queries, vectors, samples, concurrency)
                result.setdefault(lib.name, {})[method] = stats(lat)
                print(lib.name, lib.units, method, result[lib.name][method], flush=True)
            else:  # 小库：每库 20 次，按（模式, 方式）汇总
                lat = await bench_one(lib, cfg, queries, vectors, 20, concurrency)
                pooled.setdefault((lib.mode, method), []).extend(lat)
    for (mode, method), lat in sorted(pooled.items()):
        result.setdefault(f"small-{mode}", {})[method] = stats(lat)
        print(f"small-{mode}", method, result[f"small-{mode}"][method], flush=True)
    fb = vector_store.METRICS[vector_store.METRIC_HNSW_FALLBACK]
    summary = {
        "hnsw_searches": HNSW_CALLS["n"], "hnsw_fallbacks": fb,
        "fallback_ratio": round(fb / HNSW_CALLS["n"], 4) if HNSW_CALLS["n"] else None,
        "fts_cap_hit": vector_store.METRICS["kb:metrics:fts_cap_hit"],
    }  # fmt: skip
    print(
        json.dumps(
            {"concurrency": concurrency, "top_k": top_k, "summary": summary, "result": result}, ensure_ascii=False
        )
    )


async def cmd_recall(n_queries: int, seed: int, kind: str = "all") -> None:
    """HNSW（直接走 search_hnsw，不含回退）与精确检索对比 recall@10；统计返回条数不足（会触发回退）的次数。"""
    libs = [lib for lib in await load_libs() if lib.big and kind in ("all", lib.kind)]
    nrng = random.Random(seed + 11)
    factory = get_session_factory()
    groups: dict[str, list[float]] = {}
    for lib in libs:
        vectors = await sample_vectors(lib, n_queries, nrng)
        recalls: list[float] = []
        short = 0
        t_h: list[float] = []
        async with factory() as s:
            info = (await valid_indexes(s, lib.table, use_cache=False)).get(lib.model_id)
        if info is None:
            print(lib.name, "无有效索引，跳过")
            continue
        for v in vectors:
            async with factory() as s:
                st = PgVectorStore(s, model_id=lib.model_id, dimension=lib.dim, units=lib.units)
                t = time.perf_counter()
                got = await st.search_hnsw(lib.id, lib.table, v, 10, info)  # type: ignore[arg-type]
                t_h.append((time.perf_counter() - t) * 1000)
                exact = await st.search_exact(lib.id, lib.table, v, 10)
            short += len(got) < 10
            recalls.append(len({i for i, _ in got} & {i for i, _ in exact}) / max(1, len(exact)))
        groups.setdefault(lib.kind, []).extend(recalls)
        print(
            json.dumps(
                {"lib": lib.name, "kind": lib.kind, "recall_mean": round(statistics.mean(recalls), 4),
                 "recall_min": min(recalls), "queries": len(recalls), "short_results": short,
                 "hnsw_p50_ms": round(statistics.median(t_h), 1)},
                ensure_ascii=False,
            ),
            flush=True,
        )  # fmt: skip
    for kind, r in groups.items():
        print(
            json.dumps({"group": kind, "recall_mean": round(statistics.mean(r), 4), "recall_min": min(r), "n": len(r)})
        )


async def cmd_overlap(top_k: int, seed: int) -> None:
    """全文裁剪前后 Top-K 重合度（17 条查询）与结果条数检查。"""
    libs = [lib for lib in await load_libs() if lib.big]
    settings = Settings()
    queries = make_queries(seed)
    factory = get_session_factory()
    all_overlap: list[float] = []
    for lib in libs:
        common = await load_common_terms(lib.id)
        ovs: list[float] = []
        bad = 0
        miss_terms = 0
        for q in queries:
            terms = build_terms(q)
            if not terms:
                continue
            async with factory() as s:
                full = await fulltext_search(s, lib.id, lib.table, terms_to_tsquery(terms), top_k)
                pruned = await fulltext_search_pruned(
                    s, lib.id, lib.table, terms, top_k, common=common, settings=settings
                )
            if common is None:
                miss_terms += 1
            if not full:
                continue
            ovs.append(len({i for i, _ in full} & {i for i, _ in pruned}) / len(full))
            bad += len(pruned) < min(top_k, len(full))
        all_overlap.extend(ovs)
        print(
            json.dumps(
                {"lib": lib.name, "overlap_mean": round(statistics.mean(ovs), 4), "overlap_min": round(min(ovs), 2),
                 "queries": len(ovs), "count_violations": bad, "common_terms": len(common or {}),
                 "common_missing": miss_terms},
                ensure_ascii=False,
            ),
            flush=True,
        )  # fmt: skip
    print(json.dumps({"overlap_mean_all": round(statistics.mean(all_overlap), 4), "n": len(all_overlap),
                      "fts_cap_hit": vector_store.METRICS["kb:metrics:fts_cap_hit"]}))  # fmt: skip


async def cmd_explain(seed: int) -> None:
    """默认规划器设置下的 EXPLAIN：大库向量查询是否走 ix_*_hnsw_m{id}，小库是否走 ix_*_search（不 seq scan）。"""
    libs = await load_libs()
    nrng = random.Random(seed)
    factory = get_session_factory()
    seen_small: set[str] = set()
    for lib in libs:
        if not lib.big and lib.mode in seen_small:
            continue
        if not lib.big:
            seen_small.add(lib.mode)
        (v,) = await sample_vectors(lib, 1, nrng)
        async with factory() as s:
            st = PgVectorStore(s, model_id=lib.model_id, dimension=lib.dim, units=lib.units)
            info = await st.hnsw_info(lib.table)
            hnsw = info is not None
            plan = await st.explain(lib.id, lib.table, v, 10, hnsw=hnsw)
        prefix = "ix_child_" if lib.table == "child_chunk" else "ix_seg_"
        expected = f"{prefix}hnsw_m{lib.model_id}" if hnsw else f"{prefix}search"
        ok = expected in plan and "Seq Scan" not in plan
        print(
            f"[{'OK' if ok else 'FAIL'}] {lib.name} units={lib.units} path={'hnsw' if hnsw else 'exact'} expect={expected}"
        )
        short = re.sub(r"'\[[^\]]*\]'", "'[...]'", plan)
        print("   " + "\n   ".join(short.splitlines()[:6]))


# ---------------------------------------------------------------- 建索引 / 常见词 / 写入开销


async def cmd_index() -> None:
    t0 = time.perf_counter()
    res = await vector_index.reconcile(None)
    print(json.dumps({"elapsed_s": round(time.perf_counter() - t0, 1), "result": res}, ensure_ascii=False))
    async with get_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT c.relname, pg_size_pretty(pg_relation_size(c.oid)), c.reltuples::bigint FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'kb' AND c.relname LIKE '%hnsw%'"
                )
            )
        ).all()
    for r in rows:
        print("  索引", r[0], r[1], "rows≈", r[2])


async def cmd_fts() -> None:
    for lib in await load_libs():
        if not lib.big:
            continue
        t0 = time.perf_counter()
        n = await fts_stats.compute_common_terms(lib.id)
        print(lib.name, "常见词", n, f"{time.perf_counter() - t0:.1f}s", flush=True)


async def cmd_writebench(label: str, units: int, seed: int) -> None:
    """索引阶段写入开销：模拟 worker——先写 embedding + embedding_model_id（分批），再置 search_enabled。"""
    libs = await load_libs()
    m1 = libs[0].model_id
    rng = random.Random(seed)
    ds, docs = await _create_dataset(f"perf-write-{label}", "general", 20, m1)
    for start in range(0, units, BATCH):
        n = min(BATCH, units - start)
        wl = [gen_words(rng, 120) for _ in range(n)]
        await _insert_batch(
            "INSERT INTO kb.segment (dataset_id, document_id, position, segment_type, content, char_count, token_count, "
            "index_status, tsv, search_enabled, created_by, updated_by) "
            "SELECT :ds, (CAST(:docs AS bigint[]))[1 + (u.i % :nd)], u.i, 'general', u.c, 1, 1, 'pending', "
            "setweight(to_tsvector('simple', u.t), 'B'), false, :o, :o "
            "FROM unnest(CAST(:c AS text[]), CAST(:t AS text[]), CAST(:idx AS int[])) AS u(c, t, i)",
            {"ds": ds, "docs": docs, "nd": len(docs), "o": PERF_OWNER, "c": ["".join(w) for w in wl],
             "t": [" ".join(w) for w in wl], "idx": list(range(start, start + n))},
        )  # fmt: skip
    ids = [r[0] for r in await _fetch("SELECT id FROM kb.segment WHERE dataset_id = :d ORDER BY id", d=ds)]
    t0 = time.perf_counter()
    for i in range(0, len(ids), 500):
        await _insert_batch(
            "UPDATE kb.segment u SET embedding = "
            + RANDOM_VEC_SQL.replace("u.i", "u.id")
            + ", embedding_model_id = :mid, index_status = 'indexed' "
            "WHERE u.id = ANY(:ids)",
            {"dim": DIM, "mid": m1, "ids": ids[i : i + 500]},
        )
    t_embed = time.perf_counter() - t0
    t1 = time.perf_counter()
    for i in range(0, len(ids), 1000):
        await _insert_batch(
            "UPDATE kb.segment SET search_enabled = true WHERE id = ANY(:ids)", {"ids": ids[i : i + 1000]}
        )
    t_enable = time.perf_counter() - t1
    print(json.dumps({"label": label, "units": units, "embed_write_s": round(t_embed, 1), "enable_s": round(t_enable, 1),
                      "total_s": round(t_embed + t_enable, 1)}))  # fmt: skip
    await _insert_batch("DELETE FROM kb.segment WHERE dataset_id = :d", {"d": ds})
    await _insert_batch("DELETE FROM kb.document WHERE dataset_id = :d", {"d": ds})
    await _insert_batch("DELETE FROM kb.dataset WHERE id = :d", {"d": ds})


async def _fetch(sql: str, **p: object) -> list[tuple[int, ...]]:
    async with get_session_factory()() as s:
        return [tuple(r) for r in (await s.execute(text(sql), p)).all()]


async def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("seed")
    a.add_argument("--scenario", choices=["s1", "s2"], default="s1")
    a.add_argument("--units", type=int, default=100_000)
    a.add_argument("--seed", type=int, default=42)
    b = sub.add_parser("bench")
    b.add_argument("--samples", type=int, default=60)
    b.add_argument("--concurrency", type=int, default=1)
    b.add_argument("--top-k", type=int, default=5)
    b.add_argument("--seed", type=int, default=42)
    b.add_argument("--only", choices=["all", "big", "small"], default="all")
    r = sub.add_parser("recall")
    r.add_argument("--queries", type=int, default=100)
    r.add_argument("--kind", choices=["all", "random", "clustered"], default="all")
    r.add_argument("--seed", type=int, default=42)
    o = sub.add_parser("overlap")
    o.add_argument("--top-k", type=int, default=10)
    o.add_argument("--seed", type=int, default=42)
    e = sub.add_parser("explain")
    e.add_argument("--seed", type=int, default=42)
    w = sub.add_parser("writebench")
    w.add_argument("--label", required=True)
    w.add_argument("--units", type=int, default=10_000)
    w.add_argument("--seed", type=int, default=42)
    sub.add_parser("index")
    sub.add_parser("fts")
    sub.add_parser("clean")
    args = ap.parse_args()
    settings = make_settings()
    init_db(settings)
    init_redis(settings)
    try:
        if args.cmd == "seed":
            await cmd_seed(args.scenario, args.units, args.seed)
        elif args.cmd == "bench":
            await cmd_bench(args.samples, args.concurrency, args.top_k, args.seed, args.only)
        elif args.cmd == "recall":
            await cmd_recall(args.queries, args.seed, args.kind)
        elif args.cmd == "overlap":
            await cmd_overlap(args.top_k, args.seed)
        elif args.cmd == "explain":
            await cmd_explain(args.seed)
        elif args.cmd == "writebench":
            await cmd_writebench(args.label, args.units, args.seed)
        elif args.cmd == "index":
            await cmd_index()
        elif args.cmd == "fts":
            await cmd_fts()
        else:
            await cmd_clean()
    finally:
        await close_redis()
        await dispose_db()


if __name__ == "__main__":
    asyncio.run(main())
