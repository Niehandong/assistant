"""api_key / api_key_dataset 查询。

本人管理接口一律按 ``created_by = 当前用户`` 且未删除过滤（不按数据范围）；管理员审计（BE-26）在此文件追加
基于 ``data_scope_filter`` 的查询。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, and_, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApiKey, ApiKeyDataset, OrgRef, UserRef
from platform_common.auth.context import AuthContext
from platform_common.auth.data_scope import data_scope_filter


def like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def get_owned(session: AsyncSession, key_id: int, owner_id: int, *, for_update: bool = False) -> ApiKey | None:
    """本人且未删除的密钥；他人/不存在/已删除均返回 None（调用方统一 404000，防止 ID 越权）。"""
    stmt = select(ApiKey).where(ApiKey.id == key_id, ApiKey.created_by == owner_id, ApiKey.is_deleted.is_(False))
    if for_update:
        # populate_existing：同会话里此前无锁读过该行时，加锁读必须刷新为最新的 status / version
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_by_hash(session: AsyncSession, key_hash: str) -> ApiKey | None:
    """开放检索鉴权：按哈希取未删除的密钥（key_hash 唯一索引）。"""
    stmt = select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_deleted.is_(False))
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_owned(session: AsyncSession, owner_id: int, name: str | None = None) -> list[ApiKey]:
    """本人全部未删除密钥（预计 < 100），created_at 倒序。"""
    stmt = select(ApiKey).where(ApiKey.created_by == owner_id, ApiKey.is_deleted.is_(False))
    if name:
        stmt = stmt.where(ApiKey.name.like(like_pattern(name), escape="\\"))
    return list((await session.execute(stmt.order_by(ApiKey.created_at.desc(), ApiKey.id.desc()))).scalars().all())


async def name_exists(session: AsyncSession, owner_id: int, name: str, *, exclude_id: int | None = None) -> bool:
    stmt = (
        select(func.count())
        .select_from(ApiKey)
        .where(ApiKey.created_by == owner_id, ApiKey.name == name, ApiKey.is_deleted.is_(False))
    )
    if exclude_id is not None:
        stmt = stmt.where(ApiKey.id != exclude_id)
    return (await session.execute(stmt)).scalar_one() > 0


async def count_owned(session: AsyncSession, owner_id: int) -> int:
    stmt = select(func.count()).select_from(ApiKey).where(ApiKey.created_by == owner_id, ApiKey.is_deleted.is_(False))
    return int((await session.execute(stmt)).scalar_one())


async def dataset_ids_by_keys(session: AsyncSession, key_ids: Sequence[int]) -> dict[int, list[int]]:
    """批量取"指定知识库"集合（避免 N+1）。"""
    if not key_ids:
        return {}
    rows = await session.execute(
        select(ApiKeyDataset.api_key_id, ApiKeyDataset.dataset_id)
        .where(ApiKeyDataset.api_key_id.in_(list(key_ids)))
        .order_by(ApiKeyDataset.dataset_id)
    )
    out: dict[int, list[int]] = {}
    for key_id, dataset_id in rows.all():
        out.setdefault(key_id, []).append(dataset_id)
    return out


async def replace_datasets(session: AsyncSession, key_id: int, dataset_ids: Sequence[int], user_id: int) -> None:
    """整体替换指定知识库集合（关联表物理删除）。"""
    await session.execute(delete(ApiKeyDataset).where(ApiKeyDataset.api_key_id == key_id))
    session.add_all(
        [
            ApiKeyDataset(api_key_id=key_id, dataset_id=d, created_by=user_id, updated_by=user_id)
            for d in sorted(set(dataset_ids))
        ]
    )
    await session.flush()


# --------------------------------------------------------------------------- 管理员审计（BE-26）


def audit_scope(ctx: AuthContext) -> ColumnElement[bool]:
    """审计数据范围：共享库 ``data_scope_filter``（列 company_id / dept_id / created_by）。"""
    return data_scope_filter(ctx, company_col=ApiKey.company_id, dept_col=ApiKey.dept_id, owner_col=ApiKey.created_by)


def _owner_ok() -> ColumnElement[bool]:
    """创建人副本存在、启用且未删除（``owner_unavailable`` 筛选的近似口径，反向即不可用）。"""
    return exists().where(UserRef.id == ApiKey.created_by, UserRef.status == "enabled", UserRef.is_deleted.is_(False))


def audit_conditions(
    ctx: AuthContext,
    *,
    creator_keyword: str | None,
    org_id: int | None,
    status: str | None,
    now: datetime,
) -> list[ColumnElement[bool]]:
    """审计列表条件（全部绑定参数）。

    状态筛选与 ``key_status.compute`` 的优先级一致、互斥：``enabled``/``disabled``/``admin_disabled`` 看存储状态
    （``enabled`` 另要求未过期且创建人可用）；
    ``owner_unavailable`` = 存储 enabled 且创建人副本不可用（近似，不含权限码）；
    ``expired`` = 存储 enabled、创建人可用且 ``expires_at <= now``。
    """
    conds: list[ColumnElement[bool]] = [ApiKey.is_deleted.is_(False), audit_scope(ctx)]
    if creator_keyword:
        pat = like_pattern(creator_keyword)
        conds.append(
            ApiKey.created_by.in_(
                select(UserRef.id).where(
                    or_(UserRef.name.like(pat, escape="\\"), UserRef.username.like(pat, escape="\\"))
                )
            )
        )
    if org_id is not None:
        subtree = select(OrgRef.id).where(
            or_(OrgRef.id == org_id, func.concat(",", OrgRef.ancestors, ",").like(f"%,{int(org_id)},%"))
        )
        conds.append(ApiKey.dept_id.in_(subtree))
    if status in ("disabled", "admin_disabled"):
        conds.append(ApiKey.status == status)
    elif status == "owner_unavailable":
        conds.append(and_(ApiKey.status == "enabled", ~_owner_ok()))
    elif status == "expired":
        conds.append(and_(ApiKey.status == "enabled", _owner_ok(), ApiKey.expires_at <= now))
    elif status == "enabled":
        conds.append(
            and_(
                ApiKey.status == "enabled",
                _owner_ok(),
                or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > now),
            )
        )
    return conds


async def page_audit(
    session: AsyncSession, conds: Sequence[ColumnElement[bool]], *, offset: int, limit: int
) -> tuple[list[ApiKey], int]:
    total = (await session.execute(select(func.count()).select_from(ApiKey).where(*conds))).scalar_one()
    rows = (
        await session.execute(
            select(ApiKey)
            .where(*conds)
            .order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars()
    return list(rows.all()), int(total)


async def get_in_scope(
    session: AsyncSession, ctx: AuthContext, key_id: int, *, for_update: bool = False
) -> ApiKey | None:
    """数据范围内且未删除的密钥；范围外/不存在/已删除均返回 None（调用方统一 404000，防止 ID 越权）。"""
    stmt = select(ApiKey).where(ApiKey.id == key_id, ApiKey.is_deleted.is_(False), audit_scope(ctx))
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalar_one_or_none()
