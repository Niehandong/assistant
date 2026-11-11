"""组织查询与批量更新（BE-06 / BE-07）。"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import OrgType
from app.models import SysOrg


async def get_by_ids(session: AsyncSession, org_ids: Collection[int]) -> dict[int, SysOrg]:
    """含已删除节点。"""
    if not org_ids:
        return {}
    rows = (await session.scalars(select(SysOrg).where(SysOrg.id.in_(org_ids)))).all()
    return {o.id: o for o in rows}


def _descendant_cond(org_id: int):  # type: ignore[no-untyped-def]
    # ancestors 形如 "0,1,5"（不含自身）；两侧补逗号做整段匹配，避免 "1" 命中 "11"
    return func.concat(",", SysOrg.ancestors, ",").like(f"%,{int(org_id)},%")


async def descendant_company_ids(session: AsyncSession, org_id: int) -> list[int]:
    """org_id 的全部下属公司（含集团类型节点，不含自身）ID，未删除。"""
    stmt = select(SysOrg.id).where(
        _descendant_cond(org_id),
        SysOrg.org_type.in_([OrgType.GROUP, OrgType.COMPANY]),
        SysOrg.is_deleted.is_(False),
    )
    return list((await session.scalars(stmt)).all())


async def descendant_dept_ids(session: AsyncSession, org_id: int, company_id: int) -> list[int]:
    """org_id 下属的全部部门 ID（不跨入下属公司：要求部门所属公司等于 company_id），未删除。"""
    stmt = select(SysOrg.id).where(
        _descendant_cond(org_id),
        SysOrg.org_type == OrgType.DEPT,
        SysOrg.company_id == company_id,
        SysOrg.is_deleted.is_(False),
    )
    return list((await session.scalars(stmt)).all())


async def sync_page(
    session: AsyncSession, updated_after: datetime | None, after_id: int, limit: int
) -> Sequence[SysOrg]:
    """按 (updated_at, id) 升序的增量页（含已删除）；多取 1 条用于判断是否还有下一页。"""
    stmt = select(SysOrg).order_by(SysOrg.updated_at, SysOrg.id).limit(limit + 1)
    if updated_after is not None:
        stmt = stmt.where(
            or_(SysOrg.updated_at > updated_after, and_(SysOrg.updated_at == updated_after, SysOrg.id > after_id))
        )
    return (await session.scalars(stmt)).all()


# --------------------------------------------------------------------------- BE-07 组织管理


async def get_active(session: AsyncSession, org_id: int, *, for_update: bool = False) -> SysOrg | None:
    """按主键取未删除组织；``for_update`` 加行锁（写操作串行化，配合 version 校验）。"""
    stmt = select(SysOrg).where(SysOrg.id == org_id, SysOrg.is_deleted.is_(False))
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.scalars(stmt)).first()


async def list_visible(session: AsyncSession, scope_cond: ColumnElement[bool]) -> list[SysOrg]:
    """数据范围内的全部未删除组织（≤5000），按 sort_order、created_at、id 升序。"""
    stmt = (
        select(SysOrg)
        .where(SysOrg.is_deleted.is_(False), scope_cond)
        .order_by(SysOrg.sort_order, SysOrg.created_at, SysOrg.id)
    )
    return list((await session.scalars(stmt)).all())


async def name_exists(session: AsyncSession, parent_id: int, name: str, *, exclude_id: int | None = None) -> bool:
    stmt = select(SysOrg.id).where(SysOrg.parent_id == parent_id, SysOrg.name == name, SysOrg.is_deleted.is_(False))
    if exclude_id is not None:
        stmt = stmt.where(SysOrg.id != exclude_id)
    return (await session.scalars(stmt.limit(1))).first() is not None


async def code_exists(session: AsyncSession, code: str) -> bool:
    """编码唯一性含已删除。"""
    return (await session.scalars(select(SysOrg.id).where(SysOrg.code == code).limit(1))).first() is not None


async def has_children(session: AsyncSession, org_id: int) -> bool:
    stmt = select(SysOrg.id).where(SysOrg.parent_id == org_id, SysOrg.is_deleted.is_(False)).limit(1)
    return (await session.scalars(stmt)).first() is not None


async def subtree(session: AsyncSession, org_id: int, *, populate: bool = False) -> list[SysOrg]:
    """org_id 的全部未删除后代（不含自身），按 id 升序。``populate`` 强制用库中数据刷新已加载实例。"""
    stmt = select(SysOrg).where(_descendant_cond(org_id), SysOrg.is_deleted.is_(False)).order_by(SysOrg.id)
    if populate:
        stmt = stmt.execution_options(populate_existing=True)
    return list((await session.scalars(stmt)).all())


async def reparent_descendants(
    session: AsyncSession,
    *,
    old_prefix: str,
    new_prefix: str,
    ids: Sequence[int],
    company_id: int,
    operator_id: int,
) -> None:
    """批量重写后代 ancestors（前缀替换）与 company_id。

    ``old_prefix`` / ``new_prefix`` 为被移动节点"祖先路径 + 自身"（如 ``0,1,5``）。
    **显式写 updated_at / updated_by**：bulk UPDATE 不经 ORM onupdate，否则 sync 游标与事件会漏行。
    """
    if not ids:
        return
    await session.execute(
        update(SysOrg)
        .where(SysOrg.id.in_(list(ids)))
        .values(
            ancestors=func.concat(new_prefix, func.substr(SysOrg.ancestors, len(old_prefix) + 1)),
            company_id=company_id,
            updated_at=func.now(),
            updated_by=operator_id,
        )
        .execution_options(synchronize_session=False)
    )
