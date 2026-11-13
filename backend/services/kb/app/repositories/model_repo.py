"""ai_model 查询与引用统计。全局资源，不做数据权限过滤。"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import ColumnElement, Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AiModel, Dataset


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _alive() -> Select[tuple[AiModel]]:
    return select(AiModel).where(AiModel.is_deleted.is_(False))


async def get(session: AsyncSession, model_id: int, *, for_update: bool = False) -> AiModel | None:
    stmt = _alive().where(AiModel.id == model_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def name_exists(session: AsyncSession, name: str, *, exclude_id: int | None = None) -> bool:
    stmt = select(AiModel.id).where(AiModel.is_deleted.is_(False), AiModel.name == name)
    if exclude_id is not None:
        stmt = stmt.where(AiModel.id != exclude_id)
    return (await session.execute(stmt.limit(1))).first() is not None


async def page_models(
    session: AsyncSession,
    *,
    model_type: str | None,
    status: str | None,
    keyword: str | None,
    offset: int,
    limit: int,
) -> tuple[Sequence[AiModel], int]:
    conds: list[ColumnElement[bool]] = [AiModel.is_deleted.is_(False)]
    if model_type:
        conds.append(AiModel.model_type == model_type)
    if status:
        conds.append(AiModel.status == status)
    if keyword:
        conds.append(AiModel.name.like(_like(keyword), escape="\\"))
    total = (await session.execute(select(func.count()).select_from(AiModel).where(*conds))).scalar_one()
    rows = (
        (
            await session.execute(
                select(AiModel)
                .where(*conds)
                .order_by(AiModel.created_at.desc(), AiModel.id.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return rows, int(total)


async def list_enabled(session: AsyncSession, model_type: str) -> Sequence[AiModel]:
    stmt = (
        _alive()
        .where(AiModel.model_type == model_type, AiModel.status == "enabled")
        .order_by(AiModel.is_default.desc(), AiModel.id)
    )
    return (await session.execute(stmt)).scalars().all()


async def clear_default(session: AsyncSession, model_type: str, *, except_id: int | None, operator_id: int) -> None:
    stmt = (
        update(AiModel)
        .where(AiModel.model_type == model_type, AiModel.is_default.is_(True), AiModel.is_deleted.is_(False))
        .values(is_default=False, updated_by=operator_id, version=AiModel.version + 1)
    )
    if except_id is not None:
        stmt = stmt.where(AiModel.id != except_id)
    await session.execute(stmt)


# ---------------------------------------------------------------- 引用


def _ref_condition(model: AiModel):  # type: ignore[no-untyped-def]
    """引用该模型的未删除知识库条件：embedding 看 embedding_model_id，rerank 看 retrieval_config.reranking_model_id。"""
    if model.model_type == "embedding":
        return Dataset.embedding_model_id == model.id
    return Dataset.retrieval_config["reranking_model_id"].astext == str(model.id)


async def referencing_datasets(session: AsyncSession, model: AiModel, limit: int = 10) -> tuple[list[str], int]:
    cond = _ref_condition(model)
    total = (
        await session.execute(select(func.count()).select_from(Dataset).where(Dataset.is_deleted.is_(False), cond))
    ).scalar_one()
    if not total:
        return [], 0
    names = (
        (
            await session.execute(
                select(Dataset.name).where(Dataset.is_deleted.is_(False), cond).order_by(Dataset.id).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(names), int(total)


async def dataset_counts(session: AsyncSession, models: Sequence[AiModel]) -> dict[int, int]:
    """批量统计引用知识库数（每种类型一次查询，无 N+1）。"""
    counts: dict[int, int] = {m.id: 0 for m in models}
    emb_ids = [m.id for m in models if m.model_type == "embedding"]
    rr_ids = [str(m.id) for m in models if m.model_type == "rerank"]
    if emb_ids:
        rows = await session.execute(
            select(Dataset.embedding_model_id, func.count())
            .where(Dataset.is_deleted.is_(False), Dataset.embedding_model_id.in_(emb_ids))
            .group_by(Dataset.embedding_model_id)
        )
        for mid, n in rows.all():
            counts[int(mid)] = int(n)
    if rr_ids:
        ref = Dataset.retrieval_config["reranking_model_id"].astext
        rows = await session.execute(
            select(ref, func.count()).where(Dataset.is_deleted.is_(False), ref.in_(rr_ids)).group_by(ref)
        )
        for mid, n in rows.all():
            counts[int(mid)] = int(n)
    return counts
