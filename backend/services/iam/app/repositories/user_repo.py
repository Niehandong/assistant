"""用户查询（BE-06 所需部分；其余由 BE-08 补充）。"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SysRole, SysUser, SysUserRole


async def get_by_ids(session: AsyncSession, user_ids: Collection[int]) -> dict[int, SysUser]:
    """含已删除用户。"""
    if not user_ids:
        return {}
    rows = (await session.scalars(select(SysUser).where(SysUser.id.in_(user_ids)))).all()
    return {u.id: u for u in rows}


async def sync_page(
    session: AsyncSession, updated_after: datetime | None, after_id: int, limit: int
) -> Sequence[SysUser]:
    """按 (updated_at, id) 升序的增量页（含已删除）；多取 1 条用于判断是否还有下一页。"""
    stmt = select(SysUser).order_by(SysUser.updated_at, SysUser.id).limit(limit + 1)
    if updated_after is not None:
        stmt = stmt.where(
            or_(SysUser.updated_at > updated_after, and_(SysUser.updated_at == updated_after, SysUser.id > after_id))
        )
    return (await session.scalars(stmt)).all()


async def get_by_username(session: AsyncSession, username: str) -> SysUser | None:
    """按账号查未删除用户（登录用）。"""
    stmt = select(SysUser).where(SysUser.username == username, SysUser.is_deleted.is_(False))
    return (await session.scalars(stmt)).first()


async def get_by_id(session: AsyncSession, user_id: int) -> SysUser | None:
    """按主键查未删除用户。"""
    stmt = select(SysUser).where(SysUser.id == user_id, SysUser.is_deleted.is_(False))
    return (await session.scalars(stmt)).first()


async def touch_last_login(session: AsyncSession, user_id: int, ip: str | None) -> None:
    """更新最近登录信息；显式保持 updated_at 不变，避免对同步游标/事件产生噪声。"""
    await session.execute(
        update(SysUser)
        .where(SysUser.id == user_id)
        .values(last_login_at=func.now(), last_login_ip=ip, updated_at=SysUser.updated_at)
    )


async def update_password(session: AsyncSession, user: SysUser, password_hash: str) -> None:
    user.password_hash = password_hash
    user.must_change_password = False
    user.password_changed_at = datetime.now(UTC)
    user.updated_by = user.id
    await session.flush()


async def page_users_of_role(
    session: AsyncSession,
    role_id: int,
    scope_cond: ColumnElement[bool],
    offset: int,
    limit: int,
) -> tuple[list[SysUser], int]:
    """角色下的未删除用户，``scope_cond`` 为调用方生成的数据权限条件（data_scope_filter）。"""
    conds = [SysUserRole.role_id == role_id, SysUser.is_deleted.is_(False), scope_cond]
    base = select(SysUser).join(SysUserRole, SysUserRole.user_id == SysUser.id).where(*conds)
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (await session.scalars(base.order_by(SysUser.id).offset(offset).limit(limit))).all()
    return list(rows), total


# --------------------------------------------------------------------------- BE-07 组织管理所需


async def visible_user_exists(session: AsyncSession, user_id: int, scope_cond: ColumnElement[bool]) -> bool:
    """数据范围内存在未删除用户（校验负责人）。"""
    stmt = select(SysUser.id).where(SysUser.id == user_id, SysUser.is_deleted.is_(False), scope_cond).limit(1)
    return (await session.scalars(stmt)).first() is not None


async def count_in_org(session: AsyncSession, org_id: int) -> int:
    """直属该组织的未删除用户数。"""
    stmt = select(func.count()).select_from(SysUser).where(SysUser.org_id == org_id, SysUser.is_deleted.is_(False))
    return int(await session.scalar(stmt) or 0)


async def ids_in_orgs(session: AsyncSession, org_ids: Collection[int]) -> list[int]:
    """属于这些组织的未删除用户 ID。"""
    if not org_ids:
        return []
    stmt = select(SysUser.id).where(SysUser.org_id.in_(list(org_ids)), SysUser.is_deleted.is_(False))
    return list((await session.scalars(stmt)).all())


async def reassign_company(
    session: AsyncSession, org_ids: Collection[int], company_id: int, operator_id: int
) -> list[int]:
    """把这些组织下 company_id 不同的未删除用户改到 company_id，返回被更新的用户 ID。

    **显式写 updated_at / updated_by**（bulk UPDATE 不触发 ORM onupdate）。
    """
    if not org_ids:
        return []
    stmt = (
        update(SysUser)
        .where(SysUser.org_id.in_(list(org_ids)), SysUser.is_deleted.is_(False), SysUser.company_id != company_id)
        .values(company_id=company_id, updated_at=func.now(), updated_by=operator_id)
        .returning(SysUser.id)
        .execution_options(synchronize_session=False)
    )
    return [int(i) for i in (await session.scalars(stmt)).all()]


async def get_many_fresh(session: AsyncSession, user_ids: Collection[int]) -> list[SysUser]:
    """按 ID 取用户并用库中数据刷新已加载实例（bulk UPDATE 之后用）。"""
    if not user_ids:
        return []
    stmt = (
        select(SysUser)
        .where(SysUser.id.in_(list(user_ids)))
        .order_by(SysUser.id)
        .execution_options(populate_existing=True)
    )
    return list((await session.scalars(stmt)).all())


# --------------------------------------------------------------------------- BE-08 用户管理


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def get_active(session: AsyncSession, user_id: int, *, for_update: bool = False) -> SysUser | None:
    """未删除用户；``for_update`` 加行锁并用库中数据刷新。"""
    stmt = select(SysUser).where(SysUser.id == user_id, SysUser.is_deleted.is_(False))
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await session.scalars(stmt)).first()


async def username_exists(session: AsyncSession, username: str) -> bool:
    """账号全局唯一，含已删除。"""
    return (await session.scalar(select(SysUser.id).where(SysUser.username == username).limit(1))) is not None


async def mobile_exists(session: AsyncSession, mobile: str, *, exclude_id: int | None = None) -> bool:
    """未删除用户中手机号是否已被使用。"""
    stmt = select(SysUser.id).where(SysUser.mobile == mobile, SysUser.is_deleted.is_(False))
    if exclude_id is not None:
        stmt = stmt.where(SysUser.id != exclude_id)
    return (await session.scalar(stmt.limit(1))) is not None


async def page_users(
    session: AsyncSession,
    scope_cond: ColumnElement[bool],
    offset: int,
    limit: int,
    *,
    org_ids: Collection[int] | None = None,
    username: str | None = None,
    name: str | None = None,
    mobile: str | None = None,
    status: str | None = None,
) -> tuple[list[SysUser], int]:
    """分页查询未删除用户；``scope_cond`` 为调用方用 data_scope_filter 生成的数据权限条件。"""
    conds: list[ColumnElement[bool]] = [SysUser.is_deleted.is_(False), scope_cond]
    if org_ids is not None:
        conds.append(SysUser.org_id.in_(list(org_ids)))
    if username:
        conds.append(SysUser.username.ilike(_like(username), escape="\\"))
    if name:
        conds.append(SysUser.name.ilike(_like(name), escape="\\"))
    if mobile:
        conds.append(SysUser.mobile.like(_like(mobile), escape="\\"))
    if status:
        conds.append(SysUser.status == status)
    total = int(await session.scalar(select(func.count()).select_from(SysUser).where(*conds)) or 0)
    stmt = (
        select(SysUser).where(*conds).order_by(SysUser.created_at.desc(), SysUser.id.desc()).offset(offset).limit(limit)
    )
    return list((await session.scalars(stmt)).all()), total


async def roles_of_users(session: AsyncSession, user_ids: Collection[int]) -> dict[int, list[tuple[int, str]]]:
    """user_id → [(role_id, role_name)]（含停用角色，不含已删除角色），一次查询。"""
    result: dict[int, list[tuple[int, str]]] = {}
    if not user_ids:
        return result
    stmt = (
        select(SysUserRole.user_id, SysRole.id, SysRole.name)
        .join(SysRole, SysRole.id == SysUserRole.role_id)
        .where(SysUserRole.user_id.in_(list(user_ids)), SysRole.is_deleted.is_(False))
        .order_by(SysUserRole.user_id, SysRole.id)
    )
    for uid, rid, rname in (await session.execute(stmt)).all():
        result.setdefault(uid, []).append((rid, rname))
    return result


async def apply_user_roles(
    session: AsyncSession,
    user_id: int,
    org_id: int,
    *,
    add: Collection[int],
    remove: Collection[int],
    operator_id: int,
) -> None:
    """增量调整用户角色关联（物理删除/插入）。"""
    if remove:
        await session.execute(
            delete(SysUserRole).where(SysUserRole.user_id == user_id, SysUserRole.role_id.in_(list(remove)))
        )
    session.add_all(
        SysUserRole(user_id=user_id, role_id=rid, org_id=org_id, created_by=operator_id, updated_by=operator_id)
        for rid in sorted(add)
    )
    await session.flush()
