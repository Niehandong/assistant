"""角色查询与写入（BE-06 的有效角色查询 + BE-09 的角色管理）。sys_role 不受数据权限控制，可见性由 service 传入。"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import RoleType, Status
from app.models import SysPermission, SysRole, SysRoleOrg, SysRolePermission, SysUser, SysUserRole


@dataclass(frozen=True)
class EffectiveRole:
    user_id: int
    role_id: int
    builtin_key: str | None
    data_scope: str


async def effective_roles_of_users(session: AsyncSession, user_ids: Collection[int]) -> list[EffectiveRole]:
    """用户已授予且**启用、未删除**的角色。"""
    if not user_ids:
        return []
    stmt = (
        select(SysUserRole.user_id, SysRole.id, SysRole.builtin_key, SysRole.data_scope)
        .join(SysRole, SysRole.id == SysUserRole.role_id)
        .where(
            SysUserRole.user_id.in_(user_ids),
            SysRole.is_deleted.is_(False),
            SysRole.status == Status.ENABLED,
        )
    )
    return [EffectiveRole(u, r, b, d) for u, r, b, d in (await session.execute(stmt)).all()]


async def role_custom_orgs(session: AsyncSession, role_ids: Collection[int]) -> dict[int, set[int]]:
    result: dict[int, set[int]] = {}
    if not role_ids:
        return result
    stmt = select(SysRoleOrg.role_id, SysRoleOrg.org_id).where(SysRoleOrg.role_id.in_(role_ids))
    for role_id, org_id in (await session.execute(stmt)).all():
        result.setdefault(role_id, set()).add(org_id)
    return result


# --------------------------------------------------------------------------- BE-09


def visible_cond(manageable_company_ids: Collection[int] | None) -> ColumnElement[bool]:
    """角色可见条件：集团级全部可见；公司级要求 owner_company_id 在可管理公司集合内。
    ``None`` 表示不限（超管 / ALL 范围）。"""
    if manageable_company_ids is None:
        return and_(SysRole.is_deleted.is_(False))
    group = SysRole.role_type == RoleType.GROUP
    if not manageable_company_ids:
        return and_(SysRole.is_deleted.is_(False), group)
    return and_(
        SysRole.is_deleted.is_(False),
        or_(group, SysRole.owner_company_id.in_(list(manageable_company_ids))),
    )


async def get_role(session: AsyncSession, role_id: int, *, for_update: bool = False) -> SysRole | None:
    """按主键取未删除角色（不做可见性判断）。"""
    stmt = select(SysRole).where(SysRole.id == role_id, SysRole.is_deleted.is_(False))
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.scalars(stmt)).first()


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def page_roles(
    session: AsyncSession,
    *,
    manageable_company_ids: Collection[int] | None,
    name: str | None,
    code: str | None,
    role_type: str | None,
    status: str | None,
    owner_company_id: int | None,
    offset: int,
    limit: int,
) -> tuple[list[SysRole], int]:
    conds = [visible_cond(manageable_company_ids)]
    if name:
        conds.append(SysRole.name.like(_like(name), escape="\\"))
    if code:
        conds.append(SysRole.code.like(_like(code), escape="\\"))
    if role_type:
        conds.append(SysRole.role_type == role_type)
    if status:
        conds.append(SysRole.status == status)
    if owner_company_id is not None:
        conds.append(SysRole.owner_company_id == owner_company_id)
    total = int(await session.scalar(select(func.count()).select_from(SysRole).where(*conds)) or 0)
    rows = (await session.scalars(select(SysRole).where(*conds).order_by(SysRole.id).offset(offset).limit(limit))).all()
    return list(rows), total


async def list_enabled_visible_roles(
    session: AsyncSession, manageable_company_ids: Collection[int] | None
) -> list[SysRole]:
    """可分配候选：可见且启用的角色（不含权限等进一步判定）。"""
    stmt = (
        select(SysRole)
        .where(visible_cond(manageable_company_ids), SysRole.status == Status.ENABLED)
        .order_by(SysRole.id)
    )
    return list((await session.scalars(stmt)).all())


async def get_roles_by_ids(session: AsyncSession, role_ids: Collection[int]) -> list[SysRole]:
    """未删除角色（不做可见性判断）。"""
    if not role_ids:
        return []
    stmt = select(SysRole).where(SysRole.id.in_(list(role_ids)), SysRole.is_deleted.is_(False)).order_by(SysRole.id)
    return list((await session.scalars(stmt)).all())


async def count_users_by_role(session: AsyncSession, role_ids: Collection[int]) -> dict[int, int]:
    """各角色关联的**未删除**用户数。"""
    if not role_ids:
        return {}
    stmt = (
        select(SysUserRole.role_id, func.count(SysUserRole.user_id))
        .join(SysUser, SysUser.id == SysUserRole.user_id)
        .where(SysUserRole.role_id.in_(list(role_ids)), SysUser.is_deleted.is_(False))
        .group_by(SysUserRole.role_id)
    )
    return {rid: int(cnt) for rid, cnt in (await session.execute(stmt)).all()}


async def role_permissions(session: AsyncSession, role_id: int) -> dict[int, str]:
    """角色已有权限：permission_id → code（仅未删除权限点）。"""
    stmt = (
        select(SysPermission.id, SysPermission.code)
        .join(SysRolePermission, SysRolePermission.permission_id == SysPermission.id)
        .where(SysRolePermission.role_id == role_id, SysPermission.is_deleted.is_(False))
    )
    return {pid: code for pid, code in (await session.execute(stmt)).all()}


async def role_org_ids(session: AsyncSession, role_id: int) -> list[int]:
    stmt = select(SysRoleOrg.org_id).where(SysRoleOrg.role_id == role_id).order_by(SysRoleOrg.org_id)
    return list((await session.scalars(stmt)).all())


async def user_role_ids(session: AsyncSession, user_id: int) -> set[int]:
    """用户已授予的角色 ID（含停用角色，不含已删除角色）。"""
    stmt = (
        select(SysUserRole.role_id)
        .join(SysRole, SysRole.id == SysUserRole.role_id)
        .where(SysUserRole.user_id == user_id, SysRole.is_deleted.is_(False))
    )
    return set((await session.scalars(stmt)).all())


async def code_exists(session: AsyncSession, code: str) -> bool:
    """编码唯一性包含已删除角色。"""
    stmt = select(SysRole.id).where(SysRole.code == code).limit(1)
    return (await session.scalar(stmt)) is not None


async def name_exists(
    session: AsyncSession, owner_company_id: int | None, name: str, exclude_id: int | None = None
) -> bool:
    """同一归属（集团级归 0）下未删除角色名称是否重复。"""
    stmt = select(SysRole.id).where(
        func.coalesce(SysRole.owner_company_id, 0) == (owner_company_id or 0),
        SysRole.name == name,
        SysRole.is_deleted.is_(False),
    )
    if exclude_id is not None:
        stmt = stmt.where(SysRole.id != exclude_id)
    return (await session.scalar(stmt.limit(1))) is not None


async def replace_role_permissions(
    session: AsyncSession, role_id: int, permission_ids: Collection[int], operator_id: int
) -> None:
    await session.execute(delete(SysRolePermission).where(SysRolePermission.role_id == role_id))
    session.add_all(
        SysRolePermission(role_id=role_id, permission_id=pid, created_by=operator_id, updated_by=operator_id)
        for pid in sorted(permission_ids)
    )
    await session.flush()


async def replace_role_orgs(session: AsyncSession, role_id: int, org_ids: Collection[int], operator_id: int) -> None:
    await session.execute(delete(SysRoleOrg).where(SysRoleOrg.role_id == role_id))
    session.add_all(
        SysRoleOrg(role_id=role_id, org_id=oid, created_by=operator_id, updated_by=operator_id)
        for oid in sorted(org_ids)
    )
    await session.flush()


async def company_roles_owned_by(session: AsyncSession, company_id: int, limit: int = 10) -> tuple[list[str], int]:
    """归属某公司的未删除公司级角色：(最多 limit 个名称, 总数)。"""
    cond = (
        SysRole.owner_company_id == company_id,
        SysRole.role_type == RoleType.COMPANY,
        SysRole.is_deleted.is_(False),
    )
    total = int(await session.scalar(select(func.count()).select_from(SysRole).where(*cond)) or 0)
    names = (await session.scalars(select(SysRole.name).where(*cond).order_by(SysRole.id).limit(limit))).all()
    return list(names), total


async def remove_org_refs(session: AsyncSession, org_id: int) -> list[str]:
    """物理删除 sys_role_org 中引用该组织的行（CUSTOM 范围自动收窄）；返回受影响的未删除角色名称（去重、按 id 序）。"""
    rows = (
        await session.execute(
            select(SysRole.id, SysRole.name, SysRole.is_deleted)
            .join(SysRoleOrg, SysRoleOrg.role_id == SysRole.id)
            .where(SysRoleOrg.org_id == org_id)
            .order_by(SysRole.id)
        )
    ).all()
    if rows:
        await session.execute(delete(SysRoleOrg).where(SysRoleOrg.org_id == org_id))
    names: list[str] = []
    for _rid, name, deleted in rows:
        if not deleted and name not in names:
            names.append(name)
    return names
