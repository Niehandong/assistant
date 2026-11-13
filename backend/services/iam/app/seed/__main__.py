"""``python -m app.seed``：幂等初始化集团节点、权限点、内置角色、admin 用户。"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.constants import (
    ADMIN_NAME,
    ADMIN_USERNAME,
    ROOT_PARENT_ID,
    OrgType,
    RoleType,
    Status,
)
from app.core.security import hash_password
from app.models import SysOrg, SysPermission, SysRole, SysRolePermission, SysUser, SysUserRole
from app.seed.builtin import BUILTIN_ROLES
from app.seed.permission_registry import MENU_ICON_WHITELIST, PERMISSIONS
from platform_common.auth import cache_keys
from platform_common.db import create_engine, session_factory
from platform_common.redis import close_redis, get_redis, init_redis

logger = logging.getLogger("app.seed")


def validate_registry() -> None:
    """注册表自检：code 唯一、父级先于子级、菜单有图标且在白名单、按钮无图标。"""
    seen: set[str] = set()
    for p in PERMISSIONS:
        if p.code in seen:
            raise ValueError(f"权限码重复: {p.code}")
        if p.parent_code is not None and p.parent_code not in seen:
            raise ValueError(f"父级未先定义: {p.code} -> {p.parent_code}")
        if p.perm_type == "menu" and p.icon not in MENU_ICON_WHITELIST:
            raise ValueError(f"菜单图标不在白名单: {p.code} {p.icon}")
        if p.perm_type == "button" and p.icon is not None:
            raise ValueError(f"按钮不应配置图标: {p.code}")
        seen.add(p.code)


async def seed_group(session: AsyncSession, settings: Settings) -> SysOrg:
    group = await session.scalar(select(SysOrg).where(SysOrg.org_type == OrgType.GROUP, SysOrg.is_deleted.is_(False)))
    if group is not None:
        return group
    group = SysOrg(
        parent_id=ROOT_PARENT_ID,
        ancestors="0",
        org_type=OrgType.GROUP,
        name=settings.SEED_GROUP_NAME,
        code=settings.SEED_GROUP_CODE,
        status=Status.ENABLED,
        company_id=0,
        dept_id=0,
    )
    session.add(group)
    await session.flush()
    group.company_id = group.id
    group.dept_id = group.id
    await session.flush()
    logger.info("已创建集团节点 id=%s", group.id)
    return group


async def seed_permissions(session: AsyncSession) -> list[str]:
    """按 code upsert 权限点；返回本次新插入的权限码。"""
    existing = {p.code: p for p in (await session.scalars(select(SysPermission))).all()}
    id_by_code: dict[str, int] = {code: p.id for code, p in existing.items()}
    inserted: list[str] = []
    for d in PERMISSIONS:
        parent_id = id_by_code[d.parent_code] if d.parent_code else 0
        row = existing.get(d.code)
        if row is None:
            row = SysPermission(
                code=d.code,
                name=d.name,
                perm_type=d.perm_type,
                parent_id=parent_id,
                path=d.path,
                icon=d.icon,
                sort_order=d.sort_order,
                service=d.service,
            )
            session.add(row)
            await session.flush()
            inserted.append(d.code)
        else:
            row.name = d.name
            row.perm_type = d.perm_type
            row.parent_id = parent_id
            row.path = d.path
            row.icon = d.icon
            row.sort_order = d.sort_order
            row.service = d.service
        id_by_code[d.code] = row.id
    await session.flush()
    return inserted


async def seed_roles(session: AsyncSession, new_codes: list[str]) -> dict[str, SysRole]:
    """创建内置角色；已存在的角色只为本次新插入的权限点补授权。"""
    roles: dict[str, SysRole] = {}
    created_keys: set[str] = set()
    for d in BUILTIN_ROLES:
        role = await session.scalar(select(SysRole).where(SysRole.builtin_key == d.key.value))
        if role is None:
            role = SysRole(
                code=d.code,
                name=d.name,
                role_type=RoleType.GROUP,
                owner_company_id=None,
                data_scope=d.data_scope,
                status=Status.ENABLED,
                remark=d.remark,
                is_builtin=True,
                builtin_key=d.key.value,
            )
            session.add(role)
            await session.flush()
            created_keys.add(d.key.value)
        roles[d.key.value] = role

    perm_id_by_code = {c: i for c, i in (await session.execute(select(SysPermission.code, SysPermission.id))).all()}
    for pdef in PERMISSIONS:
        # 新角色：授予全部默认权限；已有角色：只补本次新插入的权限点
        for role_key in pdef.default_roles:
            if role_key.value not in created_keys and pdef.code not in new_codes:
                continue
            role = roles[role_key.value]
            granted = await session.scalar(
                select(SysRolePermission.id).where(
                    SysRolePermission.role_id == role.id, SysRolePermission.permission_id == perm_id_by_code[pdef.code]
                )
            )
            if granted is None:
                session.add(SysRolePermission(role_id=role.id, permission_id=perm_id_by_code[pdef.code]))
    await session.flush()
    return roles


async def seed_admin(session: AsyncSession, settings: Settings, group: SysOrg, super_role: SysRole) -> SysUser:
    admin = await session.scalar(select(SysUser).where(SysUser.username == ADMIN_USERNAME))
    if admin is None:
        admin = SysUser(
            username=ADMIN_USERNAME,
            password_hash=hash_password(settings.SEED_ADMIN_PASSWORD),
            name=ADMIN_NAME,
            org_id=group.id,
            company_id=group.id,
            dept_id=group.id,
            status=Status.ENABLED,
            is_builtin=True,
            must_change_password=True,
        )
        session.add(admin)
        await session.flush()
        logger.info("已创建内置管理员 admin id=%s", admin.id)
    bound = await session.scalar(
        select(SysUserRole.id).where(SysUserRole.user_id == admin.id, SysUserRole.role_id == super_role.id)
    )
    if bound is None:
        session.add(SysUserRole(user_id=admin.id, role_id=super_role.id, org_id=group.id))
        await session.flush()
    return admin


async def run_seed(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    validate_registry()
    engine = create_engine(settings)
    factory = session_factory(engine)
    try:
        async with factory() as session, session.begin():
            group = await seed_group(session, settings)
            new_codes = await seed_permissions(session)
            roles = await seed_roles(session, new_codes)
            await seed_admin(session, settings, group, roles["super_admin"])
        init_redis(settings)
        await get_redis().incr(cache_keys.AUTHZ_EPOCH)
        logger.info("seed 完成：新增权限点 %d 个", len(new_codes))
    finally:
        await close_redis()
        await engine.dispose()


def main() -> None:
    from platform_common.logging import setup_logging

    settings = get_settings()
    setup_logging(settings.SERVICE_NAME, settings.LOG_LEVEL)
    asyncio.run(run_seed(settings))


if __name__ == "__main__":
    main()
