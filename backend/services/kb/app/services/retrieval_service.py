"""检索与召回测试（F-15、F-16；tech-design-m2 3.7、5.7）。

对外入口（BE-22 内部检索接口复用）：

``await search(session, dataset, query, config) -> RetrievalResult``
* ``dataset``：已通过 ACL 校验、未删除的 ``Dataset``（本函数不判 ACL 与"无可用文档"）；
* ``config``：生效的检索设置（用 ``effective_config`` 合并默认设置与本次覆盖项）；
* 校验向量模型已启用（否则 409303）；查询向量带 Redis 缓存；Rerank 模型不存在/停用则跳过重排；
  模型服务失败 → ``BizError(503301)``，**不会**以空结果代替；
* 返回的 records 计入召回次数（Redis 累计，worker 落库）。
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.constants import ChunkMode, ModelStatus, ModelType
from app.core.security import SecretDecryptError, decrypt_secret
from app.engine.rerank import Reranker, make_reranker
from app.engine.retriever import EmbedQuery, retrieve
from app.model_clients.embedding import EmbeddingClient
from app.model_clients.errors import ModelBadResponse, ModelClientError, ModelHTTPError, ModelTimeout
from app.model_clients.rerank import RerankClient
from app.models import AiModel, Dataset
from app.repositories import model_repo, record_repo
from app.repositories.dataset_acl import require_dataset
from app.schemas.dataset import RetrievalConfig
from app.schemas.retrieval import (
    RecallRecord,
    RecallRetrievalConfig,
    RetrievalResult,
    RetrieveRecordItem,
    RetrieveTestBody,
)
from app.services.dataset_service import checked_retrieval_config
from platform_common.auth.context import AuthContext
from platform_common.db import get_session_factory
from platform_common.errors import BizError
from platform_common.redis import get_redis

logger = logging.getLogger(__name__)

ERR_MODEL_DISABLED = (409303, "向量模型已停用，请联系管理员")
ERR_NO_AVAILABLE_DOC = (409506, "知识库没有可用文档")
ERR_MODEL_CALL = 503301
HITS_SEGMENT_KEY = "kb:hits:segment"
HITS_DOCUMENT_KEY = "kb:hits:document"


def model_error(exc: ModelClientError, what: str) -> BizError:
    """模型调用错误 → 503301（原因简述不含凭据与请求内容）。"""
    if isinstance(exc, ModelTimeout):
        reason = f"{what}调用超时"
    elif isinstance(exc, ModelHTTPError):
        reason = f"{what}：{exc}" if exc.status_code is None else f"{what}返回错误（{exc}）"
    elif isinstance(exc, ModelBadResponse):
        reason = f"{what}响应不符合协议：{exc}"
    else:
        reason = f"{what}调用失败"
    return BizError(ERR_MODEL_CALL, f"模型服务调用失败：{reason}")


def effective_config(dataset: Dataset, override: RetrievalConfig | None = None) -> RetrievalConfig:
    """知识库默认设置 + 本次整体覆盖（覆盖时调用方须已用 ``checked_retrieval_config`` 校验）。"""
    return override if override is not None else RetrievalConfig.model_validate(dataset.retrieval_config or {})


def _decrypt(model: AiModel, settings: Settings) -> str | None:
    try:
        return decrypt_secret(model.api_key_encrypted, settings) if model.api_key_encrypted else None
    except SecretDecryptError as exc:
        raise BizError(ERR_MODEL_CALL, "模型服务调用失败：模型凭据无法解密") from exc


def _query_embedder(model: AiModel, settings: Settings, redis: Redis) -> EmbedQuery:
    client = EmbeddingClient(
        model.base_url, model.model_name, _decrypt(model, settings), timeout=settings.MODEL_HTTP_TIMEOUT_SECONDS
    )
    model_id, dimension = model.id, model.dimension

    async def embed(query: str) -> Sequence[float]:
        key = f"kb:qemb:{model_id}:{hashlib.sha256(query.encode()).hexdigest()}"
        try:
            cached = await redis.get(key)
            if cached:
                vec = json.loads(cached)
                if isinstance(vec, list) and (dimension is None or len(vec) == dimension):
                    return [float(v) for v in vec]
        except (RedisError, ValueError, TypeError):
            logger.warning("查询向量缓存读取失败，改为实时调用")
        try:
            vec = (await client.embed([query]))[0]
        except ModelClientError as exc:
            raise model_error(exc, "向量模型") from exc
        if dimension is not None and len(vec) != dimension:
            raise model_error(ModelBadResponse("向量维度与模型配置不一致"), "向量模型")
        try:
            await redis.set(key, json.dumps(vec), ex=settings.QUERY_EMBED_CACHE_SECONDS)
        except RedisError:
            logger.warning("查询向量缓存写入失败")
        return vec

    return embed


async def _resolve_reranker(
    session: AsyncSession, config: RetrievalConfig, settings: Settings
) -> tuple[Reranker | None, str | None]:
    """返回 (可用的重排器 | None, 模型名称 | None)。不需要重排、模型缺失/停用 → 重排器为 None。"""
    if not config.needs_rerank_model() or config.reranking_model_id is None:
        return None, None
    model = await model_repo.get(session, config.reranking_model_id)
    if model is None:
        return None, None
    if model.model_type != ModelType.RERANK or model.status != ModelStatus.ENABLED:
        return None, model.name
    client = RerankClient(
        model.base_url, model.model_name, _decrypt(model, settings), timeout=settings.MODEL_HTTP_TIMEOUT_SECONDS
    )
    inner = make_reranker(client)

    async def guarded(query: str, texts: list[str]) -> list[float]:
        try:
            return await inner(query, texts)
        except ModelClientError as exc:
            raise model_error(exc, "重排模型") from exc

    return guarded, model.name


async def record_hits(records: Sequence[RecallRecord], redis: Redis | None = None) -> None:
    """召回次数：返回的通用分段/父块及其文档各 +1（Redis 累计，worker 每 60 秒落库）。失败不影响检索。"""
    if not records:
        return
    try:
        pipe = (redis or get_redis()).pipeline()
        for r in records:
            pipe.hincrby(HITS_SEGMENT_KEY, str(r.segment_id), 1)
            pipe.hincrby(HITS_DOCUMENT_KEY, str(r.document.id), 1)
        await pipe.execute()
    except RedisError:
        logger.warning("召回次数累计失败", exc_info=True)


async def search(
    session: AsyncSession, dataset: Dataset, query: str, config: RetrievalConfig, *, settings: Settings | None = None
) -> RetrievalResult:
    s = settings or get_settings()
    dataset_id, chunk_mode = dataset.id, dataset.chunk_mode
    units = dataset.child_segment_count if chunk_mode == ChunkMode.PARENT_CHILD else dataset.segment_count
    embedding_model = await model_repo.get(session, dataset.embedding_model_id)
    if embedding_model is None or embedding_model.status != ModelStatus.ENABLED:
        raise BizError(*ERR_MODEL_DISABLED)
    reranker, rerank_name = await _resolve_reranker(session, config, s)
    embed = _query_embedder(embedding_model, s, get_redis())
    # 结束只读事务、释放连接：后面的模型 HTTP 调用可能耗时较长
    await session.commit()
    outcome = await retrieve(
        session,
        dataset_id=dataset_id,
        chunk_mode=chunk_mode,
        query=query,
        config=config,
        embed_query=embed,
        reranker=reranker,
        candidate_max=s.RETRIEVAL_CANDIDATE_MAX,
        embedding_model_id=embedding_model.id,
        dimension=embedding_model.dimension,
        units=units,
        session_factory=get_session_factory(),
        settings=s,
    )
    await record_hits(outcome.records)
    return RetrievalResult(
        query=query,
        retrieval_config=RecallRetrievalConfig(**config.model_dump(), reranking_model_name=rerank_name),
        rerank_skipped=outcome.rerank_skipped,
        rerank_skipped_reason=outcome.rerank_skipped_reason,
        records=outcome.records,
    )


async def retrieve_test(
    session: AsyncSession, ctx: AuthContext, dataset_id: int, body: RetrieveTestBody
) -> RetrievalResult:
    """5.7.1：ACL 只读；409506 → 409303；记录最近 20 条；计入召回次数。"""
    dataset = await require_dataset(session, ctx, dataset_id, "read")
    if dataset.available_doc_count <= 0:
        raise BizError(*ERR_NO_AVAILABLE_DOC)
    override = await checked_retrieval_config(session, body.retrieval_config) if body.retrieval_config else None
    config = effective_config(dataset, override)
    user_id = ctx.user_id
    result = await search(session, dataset, body.query, config)
    await record_repo.add_record(
        session,
        dataset_id=dataset_id,
        user_id=user_id,
        query=body.query,
        config=config.model_dump(),
        result_count=len(result.records),
    )
    await session.commit()
    logger.info(
        "召回测试",
        extra={
            "dataset_id": dataset_id,
            "user_id": user_id,
            "method": config.search_method,
            "hits": len(result.records),
        },
    )
    return result


async def list_records(session: AsyncSession, ctx: AuthContext, dataset_id: int) -> list[RetrieveRecordItem]:
    """5.7.2：ACL 只读；仅本人，最多 20 条，created_at 倒序。"""
    await require_dataset(session, ctx, dataset_id, "read")
    rows = await record_repo.list_recent(session, dataset_id, ctx.user_id)
    return [
        RetrieveRecordItem(
            id=r.id,
            query=r.query,
            search_method=(r.retrieval_config or {}).get("search_method", "vector"),
            retrieval_config=RetrievalConfig.model_validate(r.retrieval_config),
            result_count=r.result_count,
            created_at=r.created_at,
        )
        for r in rows
    ]
