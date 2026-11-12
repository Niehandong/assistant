"""kb 内部接口业务（tech-design-m2 5.9），供 open 服务（API 密钥检索）与 iam 统计调用。

* ACL 一律按"用户当前"的 AuthContext 实时计算（``load_auth_context``，不依赖只读副本、不缓存结果）；
  用户不存在/停用/删除/组织链停用 → 视为无访问权（404000 / 空数组）。
* 检索只调用 ``retrieval_service.search`` 入口。
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ModelStatus
from app.repositories import internal_repo, model_repo
from app.repositories.dataset_acl import require_dataset
from app.schemas.dataset import RetrievalConfig
from app.schemas.internal import (
    AccessibleBody,
    AccessibleResult,
    BriefBody,
    CountResult,
    DatasetBrief,
    DatasetRef,
    InternalRetrievalResult,
    InternalRetrieveBody,
)
from app.schemas.retrieval import RecallRetrievalConfig
from app.services import retrieval_service
from platform_common.auth.context import AuthContext, load_auth_context
from platform_common.errors import BizError, CommonErrors

_LOAD_CONCURRENCY = 20


async def _usable_ctx(user_id: int) -> AuthContext | None:
    ctx = await load_auth_context(user_id)
    return ctx if ctx is not None and ctx.usable else None


def _merge(default: RetrievalConfig, body: InternalRetrieveBody) -> RetrievalConfig:
    data = default.model_dump()
    o = body.overrides
    if o is not None:
        if o.search_method is not None:
            data["search_method"] = o.search_method
        if o.top_k is not None:
            data["top_k"] = o.top_k
        if o.score_threshold is not None:
            data["score_threshold"] = round(o.score_threshold, 2)
            data["score_threshold_enabled"] = True
        if o.reranking_enable is not None:
            data["reranking_enable"] = o.reranking_enable
    try:
        return RetrievalConfig(**data).normalized()
    except ValueError as exc:
        raise BizError(*CommonErrors.INVALID_PARAMS) from exc


async def retrieve(session: AsyncSession, dataset_id: int, body: InternalRetrieveBody) -> InternalRetrievalResult:
    ctx = await _usable_ctx(body.user_id)
    if ctx is None:
        raise BizError(*CommonErrors.NOT_FOUND)
    dataset = await require_dataset(session, ctx, dataset_id, "read")  # 不可访问/已删除 → 404000
    ref = DatasetRef(id=dataset.id, name=dataset.name)
    default = retrieval_service.effective_config(dataset)
    config = _merge(default, body)
    model = await model_repo.get(session, dataset.embedding_model_id)
    if model is None or model.status != ModelStatus.ENABLED:
        raise BizError(*retrieval_service.ERR_MODEL_DISABLED)
    if dataset.available_doc_count <= 0:  # 无可用文档：空结果，不报错
        return InternalRetrievalResult(
            query=body.query,
            retrieval_config=RecallRetrievalConfig(**config.model_dump()),
            rerank_skipped=False,
            rerank_skipped_reason=None,
            records=[],
            dataset=ref,
        )
    result = await retrieval_service.search(session, dataset, body.query, config)
    return InternalRetrievalResult(**result.model_dump(), dataset=ref)


async def accessible_datasets(session: AsyncSession, body: AccessibleBody) -> AccessibleResult:
    user_ids = list(dict.fromkeys(body.user_ids))
    sem = asyncio.Semaphore(_LOAD_CONCURRENCY)

    async def load(uid: int) -> AuthContext | None:
        async with sem:
            return await _usable_ctx(uid)

    ctxs = await asyncio.gather(*(load(uid) for uid in user_ids))
    items: dict[str, list[int]] = {}
    for uid, ctx in zip(user_ids, ctxs, strict=True):
        items[str(uid)] = [] if ctx is None else await internal_repo.accessible_ids(session, ctx, body.dataset_ids)
    return AccessibleResult(items=items)


async def briefs(session: AsyncSession, body: BriefBody) -> list[DatasetBrief]:
    rows = await internal_repo.briefs(session, list(dict.fromkeys(body.ids)))
    return [DatasetBrief(id=i, name=n, is_deleted=d) for i, n, d in rows]


async def stats(session: AsyncSession, dept_id: int | None, owner_id: int | None) -> CountResult:
    if (dept_id is None) == (owner_id is None):
        raise BizError(*CommonErrors.INVALID_PARAMS)
    if dept_id is not None:
        return CountResult(count=await internal_repo.count_by_dept(session, dept_id))
    assert owner_id is not None
    return CountResult(count=await internal_repo.count_by_owner(session, owner_id))
