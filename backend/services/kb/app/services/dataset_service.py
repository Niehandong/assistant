"""知识库业务（F-08、F-09、F-15）：我的列表、创建、编辑、检索设置、删除。

约定：
* 日常访问一律走 ``dataset_acl``（所有者 + 分配），写操作在事务内 ``FOR UPDATE`` 锁行后重新校验 ACL 与 version。
* 功能权限码由路由层声明；级别不足 403311，不可访问 404000。
* 自行转移见 ``transfer_service``（BE-23）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ModelStatus, ModelType
from app.models import AiModel, Dataset, OrgRef, UserRef
from app.repositories import dataset_repo, model_repo
from app.repositories.dataset_acl import Level, resolve_dataset
from app.repositories.dataset_repo import DatasetFilter
from app.schemas.dataset import (
    DatasetCreate,
    DatasetDeleteBody,
    DatasetDetail,
    DatasetItem,
    DatasetOption,
    DatasetUpdate,
    ModelBrief,
    OwnerBrief,
    OwnerOrg,
    RetrievalConfig,
    RetrievalConfigUpdate,
)
from platform_common.auth.context import AuthContext
from platform_common.errors import BizError, CommonErrors
from platform_common.oplog import oplog_scope
from platform_common.pagination import PageParams

ERR_NEED_ENABLED_MODEL = (400303, "请选择已启用的模型")
ERR_CONFIRM_NAME = (400311, "输入的名称与知识库名称不一致")
ERR_DUP_NAME = (409311, "您已有同名知识库")
ERR_HAS_DOCS = (409312, "已有文档，暂不支持更换向量模型")
ERR_LEVEL_DENIED = (403311, "您对该知识库没有此操作权限")
UQ_DATASET_NAME = "uq_dataset_owner_name"


# ---------------------------------------------------------------- 序列化


def _owner_brief(ctx: AuthContext, owner_id: int, owners: dict[int, UserRef]) -> OwnerBrief:
    u = owners.get(owner_id)
    if u is not None:
        status = "deleted" if u.is_deleted else ("disabled" if u.status != "enabled" else "enabled")
        return OwnerBrief(id=u.id, name=u.name, status=status)  # type: ignore[arg-type]
    if owner_id == ctx.user_id:  # 刚创建、副本尚未同步
        return OwnerBrief(id=owner_id, name=ctx.name, status="enabled")
    return OwnerBrief(id=owner_id, name="未知用户", status="deleted")


def _model_brief(model_id: int, models: dict[int, AiModel]) -> ModelBrief:
    m = models.get(model_id)
    if m is None:
        return ModelBrief(id=model_id, name="", status="disabled")
    status = ModelStatus.ENABLED if (m.status == ModelStatus.ENABLED and not m.is_deleted) else ModelStatus.DISABLED
    return ModelBrief(id=m.id, name=m.name, status=status.value)


def _item_fields(
    ctx: AuthContext, d: Dataset, perm: Level, owners: dict[int, UserRef], models: dict[int, AiModel]
) -> dict[str, Any]:
    return {
        "id": d.id,
        "name": d.name,
        "description": d.description,
        "icon": d.icon,
        "owner": _owner_brief(ctx, d.owner_id, owners),
        "my_permission": perm,
        "chunk_mode": d.chunk_mode,
        "indexing_technique": d.indexing_technique,
        "search_method": (d.retrieval_config or {}).get("search_method", "vector"),
        "doc_count": d.doc_count,
        "processing_count": d.processing_count,
        "failed_count": d.failed_count,
        "available_doc_count": d.available_doc_count,
        "segment_count": d.segment_count,
        "child_segment_count": d.child_segment_count,
        "char_count": d.char_count,
        "embedding_model": _model_brief(d.embedding_model_id, models),
        "created_at": d.created_at,
        "updated_at": d.updated_at,
    }


async def _items(session: AsyncSession, ctx: AuthContext, rows: Sequence[tuple[Dataset, str]]) -> list[DatasetItem]:
    owners = await dataset_repo.owners_by_id(session, [d.owner_id for d, _ in rows])
    models = await dataset_repo.models_by_id(session, [d.embedding_model_id for d, _ in rows])
    return [DatasetItem(**_item_fields(ctx, d, p, owners, models)) for d, p in rows]  # type: ignore[arg-type]


async def _detail(session: AsyncSession, ctx: AuthContext, d: Dataset, perm: Level) -> DatasetDetail:
    """详情（刷新后的行）。调用前须保证 updated_at 等库生成列已加载（commit 后 refresh）。"""
    owners = await dataset_repo.owners_by_id(session, [d.owner_id])
    models = await dataset_repo.models_by_id(session, [d.embedding_model_id])
    orgs: dict[int, OrgRef] = await dataset_repo.orgs_by_id(session, [d.company_id, d.dept_id])
    company, dept = orgs.get(d.company_id), orgs.get(d.dept_id)
    return DatasetDetail(
        **_item_fields(ctx, d, perm, owners, models),
        retrieval_config=RetrievalConfig.model_validate(d.retrieval_config),
        last_process_rule=d.last_process_rule,
        owner_org=OwnerOrg(
            company_id=d.company_id,
            company_name=company.name if company else "",
            dept_id=d.dept_id,
            dept_name=dept.name if dept else "",
        ),
        assignment_count=await dataset_repo.assignment_count(session, d.id),
        version=d.version,
    )


build_detail = _detail  # 供转移服务复用


# ---------------------------------------------------------------- 校验辅助


async def _usable_model(session: AsyncSession, model_id: int, model_type: ModelType) -> AiModel:
    m = await model_repo.get(session, model_id)
    if m is None or m.model_type != model_type or m.status != ModelStatus.ENABLED:
        raise BizError(*ERR_NEED_ENABLED_MODEL)
    return m


async def _default_embedding(session: AsyncSession) -> AiModel:
    models = await model_repo.list_enabled(session, ModelType.EMBEDDING)
    for m in models:
        if m.is_default:
            return m
    raise BizError(*ERR_NEED_ENABLED_MODEL)


async def _checked_config(session: AsyncSession, cfg: RetrievalConfig) -> RetrievalConfig:
    """规范化并校验 Rerank 模型引用（须为启用的 rerank 模型，否则 400303）。"""
    cfg = cfg.normalized()
    if cfg.needs_rerank_model():
        if cfg.reranking_model_id is None:
            raise BizError(*ERR_NEED_ENABLED_MODEL)
        await _usable_model(session, cfg.reranking_model_id, ModelType.RERANK)
    return cfg


checked_retrieval_config = _checked_config  # 供召回测试等复用（覆盖设置的校验同 5.2.6）


async def _commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if UQ_DATASET_NAME in str(getattr(exc.orig, "constraint_name", "") or exc.orig):
            raise BizError(*ERR_DUP_NAME) from exc
        raise


def _locked_version(d: Dataset, version: int) -> None:
    if d.version != version:
        raise BizError(*CommonErrors.VERSION_CONFLICT)


# ---------------------------------------------------------------- 查询


async def list_my_datasets(
    session: AsyncSession, ctx: AuthContext, pp: PageParams, f: DatasetFilter
) -> tuple[list[DatasetItem], int]:
    rows, total = await dataset_repo.page_my_datasets(session, ctx, f, offset=pp.offset, limit=pp.limit)
    return await _items(session, ctx, rows), total


async def list_options(
    session: AsyncSession, ctx: AuthContext, keyword: str | None, pp: PageParams
) -> tuple[list[DatasetOption], int]:
    rows, total = await dataset_repo.page_options(session, ctx, keyword, offset=pp.offset, limit=pp.limit)
    return [DatasetOption(id=i, name=n, my_permission=p) for i, n, p in rows], total  # type: ignore[arg-type]


async def get_detail(session: AsyncSession, ctx: AuthContext, dataset_id: int) -> DatasetDetail:
    d, level = await resolve_dataset(session, ctx, dataset_id, "read")
    return await _detail(session, ctx, d, level)


# ---------------------------------------------------------------- 写操作


async def create_dataset(
    session: AsyncSession, ctx: AuthContext, request: Request, body: DatasetCreate
) -> DatasetDetail:
    async with oplog_scope(
        request, ctx, module="dataset", action="create", target_type="dataset", target_name=body.name
    ) as h:
        if body.embedding_model_id is None:
            model = await _default_embedding(session)
        else:
            model = await _usable_model(session, body.embedding_model_id, ModelType.EMBEDDING)
        cfg = await _checked_config(session, body.retrieval_config or RetrievalConfig())
        if await dataset_repo.name_taken(session, ctx.user_id, body.name):
            raise BizError(*ERR_DUP_NAME)
        d = Dataset(
            name=body.name,
            description=body.description,
            icon=body.icon,
            owner_id=ctx.user_id,
            company_id=ctx.company_id,
            dept_id=ctx.org_id,
            embedding_model_id=model.id,
            chunk_mode=None,
            retrieval_config=cfg.model_dump(),
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
        )
        session.add(d)
        await _flush_commit(session)
        await session.refresh(d)
        h.set_target(d.id, d.name)
        h.summary = {"after": {"name": d.name, "embedding_model": model.name, "search_method": cfg.search_method}}
        return await _detail(session, ctx, d, "owner")


async def _flush_commit(session: AsyncSession) -> None:
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if UQ_DATASET_NAME in str(getattr(exc.orig, "constraint_name", "") or exc.orig):
            raise BizError(*ERR_DUP_NAME) from exc
        raise
    await _commit(session)


async def update_dataset(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, body: DatasetUpdate
) -> DatasetDetail:
    async with oplog_scope(
        request, ctx, module="dataset", action="update", target_type="dataset", target_id=dataset_id
    ) as h:
        d, level = await resolve_dataset(session, ctx, dataset_id, "edit", for_update=True)
        h.set_target(d.id, d.name)
        _locked_version(d, body.version)
        before: dict[str, Any] = {"name": d.name, "description": d.description, "icon": d.icon}
        fields = body.model_fields_set
        if body.embedding_model_id is not None and body.embedding_model_id != d.embedding_model_id:
            if level != "owner":
                raise BizError(*ERR_LEVEL_DENIED)
            if await dataset_repo.has_documents(session, d.id):
                raise BizError(*ERR_HAS_DOCS)
            new_model = await _usable_model(session, body.embedding_model_id, ModelType.EMBEDDING)
            before["embedding_model_id"] = d.embedding_model_id
            d.embedding_model_id = new_model.id
        if body.name != d.name:
            if await dataset_repo.name_taken(session, d.owner_id, body.name, exclude_id=d.id):
                raise BizError(*ERR_DUP_NAME)
            d.name = body.name
        if "description" in fields:
            d.description = body.description
        if "icon" in fields:
            d.icon = body.icon
        d.version += 1
        d.updated_by = ctx.user_id
        await _commit(session)
        await session.refresh(d)
        after: dict[str, Any] = {"name": d.name, "description": d.description, "icon": d.icon}
        if "embedding_model_id" in before:
            after["embedding_model_id"] = d.embedding_model_id
        keys = [k for k in after if before.get(k) != after[k]]
        h.summary = {"before": {k: before[k] for k in keys}, "after": {k: after[k] for k in keys}}
        return await _detail(session, ctx, d, level)


async def update_retrieval_config(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, body: RetrievalConfigUpdate
) -> DatasetDetail:
    async with oplog_scope(
        request, ctx, module="dataset", action="retrieval_config", target_type="dataset", target_id=dataset_id
    ) as h:
        d, level = await resolve_dataset(session, ctx, dataset_id, "edit", for_update=True)
        h.set_target(d.id, d.name)
        _locked_version(d, body.version)
        cfg = await _checked_config(session, body.retrieval_config)
        before = dict(d.retrieval_config or {})
        after = cfg.model_dump()
        d.retrieval_config = after
        d.version += 1
        d.updated_by = ctx.user_id
        await _commit(session)
        await session.refresh(d)
        keys = [k for k in after if before.get(k) != after[k]]
        h.summary = {"before": {k: before.get(k) for k in keys}, "after": {k: after[k] for k in keys}}
        return await _detail(session, ctx, d, level)


async def delete_dataset(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, body: DatasetDeleteBody
) -> None:
    async with oplog_scope(
        request, ctx, module="dataset", action="delete", target_type="dataset", target_id=dataset_id
    ) as h:
        # 仅所有者；超级管理员放行 ACL（F-09 规则 7），仍需确认名称
        d, _ = await resolve_dataset(session, ctx, dataset_id, "owner", for_update=True, allow_super_admin=True)
        h.set_target(d.id, d.name)
        if body.confirm_name != d.name:
            raise BizError(*ERR_CONFIRM_NAME)
        assignments = await dataset_repo.assignment_count(session, d.id)
        await dataset_repo.soft_delete_cascade(session, d.id, ctx.user_id)
        d.is_deleted = True
        d.updated_by = ctx.user_id
        d.version += 1
        await session.commit()
        h.summary = {"before": {"name": d.name, "doc_count": d.doc_count}, "assignment_count": assignments}
