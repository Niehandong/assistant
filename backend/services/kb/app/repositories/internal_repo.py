"""内部接口查询（不受数据权限控制；调用方为受信任的内部服务）。"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dataset, OrgRef
from app.repositories.assignment_repo import descendant_cond
from app.repositories.dataset_acl import accessible_dataset_ids_subquery
from platform_common.auth.context import AuthContext


async def accessible_ids(session: AsyncSession, ctx: AuthContext, dataset_ids: Sequence[int] | None) -> list[int]:
    stmt = accessible_dataset_ids_subquery(ctx)
    if dataset_ids is not None:
        stmt = stmt.where(Dataset.id.in_(set(dataset_ids)))
    return sorted((await session.execute(stmt)).scalars().all())


async def briefs(session: AsyncSession, ids: Sequence[int]) -> list[tuple[int, str, bool]]:
    rows = (
        await session.execute(
            select(Dataset.id, Dataset.name, Dataset.is_deleted).where(Dataset.id.in_(set(ids))).order_by(Dataset.id)
        )
    ).all()
    return [(int(r[0]), r[1], bool(r[2])) for r in rows]


async def count_by_dept(session: AsyncSession, dept_id: int) -> int:
    """该组织节点及其下级节点下的未删除知识库数（知识库 dept_id = 所有者主组织）。"""
    sub = select(OrgRef.id).where(descendant_cond(dept_id))
    stmt = select(func.count()).select_from(Dataset).where(Dataset.is_deleted.is_(False), Dataset.dept_id.in_(sub))
    n = int((await session.execute(stmt)).scalar_one())
    direct = select(func.count()).select_from(Dataset).where(Dataset.is_deleted.is_(False), Dataset.dept_id == dept_id)
    return max(n, int((await session.execute(direct)).scalar_one()))  # 副本中缺该节点时仍按直属计数


async def count_by_owner(session: AsyncSession, owner_id: int) -> int:
    stmt = select(func.count()).select_from(Dataset).where(Dataset.is_deleted.is_(False), Dataset.owner_id == owner_id)
    return int((await session.execute(stmt)).scalar_one())
