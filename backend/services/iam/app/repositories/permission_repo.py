"""权限点查询（sys_permission 不受数据权限控制）。"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SysPermission, SysRolePermission


async def list_all(session: AsyncSession) -> Sequence[SysPermission]:
    """全部未删除权限点，按 (sort_order, id) 排序。"""
    stmt = (
        select(SysPermission)
        .where(SysPermission.is_deleted.is_(False))
        .order_by(SysPermission.sort_order, SysPermission.id)
    )
    return (await session.scalars(stmt)).all()


async def list_all_codes(session: AsyncSession) -> list[str]:
    stmt = select(SysPermission.code).where(SysPermission.is_deleted.is_(False)).order_by(SysPermission.code)
    return list((await session.scalars(stmt)).all())


async def role_permission_codes(session: AsyncSession, role_ids: Collection[int]) -> dict[int, set[str]]:
    """role_id → 权限码集合（仅未删除的权限点）。"""
    result: dict[int, set[str]] = {}
    if not role_ids:
        return result
    stmt = (
        select(SysRolePermission.role_id, SysPermission.code)
        .join(SysPermission, SysPermission.id == SysRolePermission.permission_id)
        .where(SysRolePermission.role_id.in_(role_ids), SysPermission.is_deleted.is_(False))
    )
    for role_id, code in (await session.execute(stmt)).all():
        result.setdefault(role_id, set()).add(code)
    return result


async def get_by_ids(session: AsyncSession, permission_ids: Collection[int]) -> dict[int, SysPermission]:
    """未删除权限点。"""
    if not permission_ids:
        return {}
    stmt = select(SysPermission).where(SysPermission.id.in_(list(permission_ids)), SysPermission.is_deleted.is_(False))
    return {p.id: p for p in (await session.scalars(stmt)).all()}
