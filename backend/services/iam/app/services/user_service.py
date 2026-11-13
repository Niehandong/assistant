"""用户管理（5.3）：列表/详情、新增、编辑、启停、重置密码、分配角色、删除、影响提示。

约定：
* 单个用户读写统一先 ``_get_visible``（未删除且在数据范围内，否则 404000，防止通过 ID 越权）。
* 写操作 ``SELECT ... FOR UPDATE`` 后再校验 ``version``（409001）。
* 修改 ``sys_user`` 的路径（新增/编辑/启停/重置密码/删除）都发布 ``user.upserted``；分配角色不改用户行，不发布。
* 要求即时生效的路径（停用/删除/重置密码）：``revoke_all`` → ``commit`` → ``purge_cache`` → ``invalidate_user``。
* 初始密码/重置密码只出现在响应中，操作日志摘要不含任何密码字段。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import RevokeReason, Status
from app.core.security import generate_password, hash_password
from app.models import SysOrg, SysRole, SysUser
from app.repositories import org_repo, permission_repo, role_repo, scope, user_repo
from app.schemas.user import (
    AssignRolesBody,
    PasswordReset,
    ResetPasswordBody,
    RoleRef,
    UserCreate,
    UserCreated,
    UserImpact,
    UserItem,
    UserStatusBody,
    UserUpdate,
)
from app.services import authz_service, downstream, event_service, role_service, session_service
from app.services.auth_service import password_rule_errors
from platform_common.auth.context import AuthContext
from platform_common.errors import BizError, CommonErrors
from platform_common.oplog import oplog_scope
from platform_common.pagination import PageParams

logger = logging.getLogger(__name__)

PASSWORD_INVALID = (400102, "密码不符合规则")
USER_PROTECTED_SELF = (403111, "不能停用或删除自己")
USER_PROTECTED_BUILTIN = (403112, "不能停用或删除内置管理员账号")
USERNAME_EXISTS = (409111, "账号已存在")
MOBILE_EXISTS = (409112, "手机号已被使用")
SELF_LOCKOUT = (409124, "保存后您将失去该页面权限，请确认")
# 自锁检查关注的权限（5.3.7）
_LOCKOUT_WATCH = ("system:role:list", "system:user:list")


# --------------------------------------------------------------------------- 内部工具


def _not_found() -> BizError:
    return BizError(*CommonErrors.NOT_FOUND)


def _forbidden() -> BizError:
    return BizError(*CommonErrors.FORBIDDEN)


async def _get_visible(session: AsyncSession, ctx: AuthContext, user_id: int, *, for_update: bool = False) -> SysUser:
    """查询用：可见范围（含 SELF 本人账号特例），范围外 404000。"""
    user = await user_repo.get_active(session, user_id, for_update=for_update) if user_id > 0 else None
    if user is None or not scope.user_visible(ctx, user):
        raise _not_found()
    return user


async def _get_manageable(
    session: AsyncSession, ctx: AuthContext, user_id: int, *, for_update: bool = False
) -> SysUser:
    """写操作用：只认管理范围。完全不可见 404000；可见但不可管理 403001。"""
    user = await _get_visible(session, ctx, user_id, for_update=for_update)
    if not scope.user_manageable(ctx, user):
        raise _forbidden()
    return user


async def _get_manageable_org(session: AsyncSession, ctx: AuthContext, org_id: int) -> SysOrg:
    org = await org_repo.get_active(session, org_id)
    if org is None or not scope.org_visible(ctx, org):
        raise _not_found()
    if not scope.org_manageable(ctx, org):
        raise _forbidden()
    return org


def _ensure_version(user: SysUser, version: int) -> None:
    if user.version != version:
        raise BizError(*CommonErrors.VERSION_CONFLICT)


def _password_error(password: str) -> BizError:
    errors = password_rule_errors(password)
    return BizError(
        PASSWORD_INVALID[0],
        PASSWORD_INVALID[1],
        {"errors": [{"field": "password", "message": m} for m in errors]},
    )


async def _prepare_password(password: str | None) -> tuple[str, str | None]:
    """返回 (密码哈希, 系统生成的明文或 None)。传入的密码须符合规则（400102）。"""
    generated: str | None = None
    if password is None:
        generated = generate_password(12)
        plain = generated
    else:
        if password_rule_errors(password):
            raise _password_error(password)
        plain = password
    hashed = await asyncio.to_thread(hash_password, plain)
    return hashed, generated


async def _flush_user(session: AsyncSession) -> None:
    """flush，并发下的唯一约束冲突转换为业务错误。"""
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        msg = str(exc.orig)
        if "uq_sys_user_mobile" in msg:
            raise BizError(*MOBILE_EXISTS) from exc
        if "sys_user_username_key" in msg:
            raise BizError(*USERNAME_EXISTS) from exc
        raise


async def _invalidate_quietly(user_id: int) -> None:
    """提交后立即使该用户权限上下文失效；Redis 异常只记日志（缓存 TTL 兜底）。"""
    try:
        await authz_service.invalidate_user(user_id)
    except Exception:
        logger.error("删除 authz:ctx 失败 user_id=%s", user_id, exc_info=True)


async def _purge_quietly(user_id: int, sids: list[str]) -> None:
    try:
        await session_service.purge_cache(user_id, sids)
    except BizError:
        logger.error("清理会话缓存失败 user_id=%s", user_id)


async def _to_items(session: AsyncSession, ctx: AuthContext, users: list[SysUser]) -> list[UserItem]:
    """批量组装 UserItem：组织名与角色各一次查询（无 N+1）。"""
    if not users:
        return []
    orgs = await org_repo.get_by_ids(session, {u.org_id for u in users} | {u.company_id for u in users})
    roles = await user_repo.roles_of_users(session, [u.id for u in users])
    return [
        UserItem(
            id=u.id,
            username=u.username,
            name=u.name,
            org_id=u.org_id,
            org_name=orgs[u.org_id].name if u.org_id in orgs else None,
            company_id=u.company_id,
            company_name=orgs[u.company_id].name if u.company_id in orgs else None,
            roles=[RoleRef(id=rid, name=rname) for rid, rname in roles.get(u.id, [])],
            mobile=u.mobile,
            email=u.email,
            status=u.status,
            is_builtin=u.is_builtin,
            must_change_password=u.must_change_password,
            last_login_at=u.last_login_at,
            created_at=u.created_at,
            version=u.version,
            manageable=scope.user_manageable(ctx, u),
        )
        for u in users
    ]


async def _item_of(session: AsyncSession, ctx: AuthContext, user: SysUser) -> UserItem:
    await session.refresh(user)
    return (await _to_items(session, ctx, [user]))[0]


def _snapshot(user: SysUser) -> dict[str, Any]:
    return {
        "username": user.username,
        "name": user.name,
        "org_id": user.org_id,
        "mobile": user.mobile,
        "email": user.email,
        "status": user.status,
    }


# --------------------------------------------------------------------------- 查询


async def list_users(
    session: AsyncSession,
    ctx: AuthContext,
    pp: PageParams,
    *,
    org_id: int | None,
    username: str | None,
    name: str | None,
    mobile: str | None,
    status: str | None,
) -> tuple[list[UserItem], int]:
    org_ids: list[int] | None = None
    if org_id is not None:
        # 组织树筛选：该节点及全部下级；节点不存在则无结果（可见性由数据权限条件兜底，不额外泄露）
        org = await org_repo.get_active(session, org_id)
        if org is None:
            return [], 0
        org_ids = [org.id, *(o.id for o in await org_repo.subtree(session, org.id))]
    users, total = await user_repo.page_users(
        session,
        scope.visible_user_filter(ctx),
        pp.offset,
        pp.limit,
        org_ids=org_ids,
        username=username,
        name=name,
        mobile=mobile,
        status=status,
    )
    return await _to_items(session, ctx, users), total


async def get_user(session: AsyncSession, ctx: AuthContext, user_id: int) -> UserItem:
    user = await _get_visible(session, ctx, user_id)
    return (await _to_items(session, ctx, [user]))[0]


async def impact(session: AsyncSession, ctx: AuthContext, user_id: int) -> UserImpact:
    user = await _get_manageable(session, ctx, user_id)
    datasets, keys = await asyncio.gather(
        downstream.kb_dataset_count_by_owner_safe(user.id),
        downstream.open_api_key_count_by_user_safe(user.id),
    )
    return UserImpact(owned_dataset_count=datasets, api_key_count=keys, degraded=datasets is None or keys is None)


# --------------------------------------------------------------------------- 写操作


async def create_user(session: AsyncSession, ctx: AuthContext, request: Request, body: UserCreate) -> UserCreated:
    async with oplog_scope(
        request, ctx, module="user", action="create", target_type="user", target_name=body.username
    ) as h:
        org = await _get_manageable_org(session, ctx, body.org_id)
        roles: list[SysRole] = []
        if body.role_ids:
            roles = await role_service.ensure_roles_assignable(session, ctx, body.role_ids, org_id=org.id)
        if await user_repo.username_exists(session, body.username):
            raise BizError(*USERNAME_EXISTS)
        if body.mobile and await user_repo.mobile_exists(session, body.mobile):
            raise BizError(*MOBILE_EXISTS)
        password_hash, generated = await _prepare_password(body.password)

        user = SysUser(
            username=body.username,
            password_hash=password_hash,
            name=body.name,
            org_id=org.id,
            company_id=org.company_id,
            dept_id=org.id,
            mobile=body.mobile,
            email=body.email,
            status=body.status,
            must_change_password=True,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
        )
        session.add(user)
        await _flush_user(session)
        h.set_target(user.id, user.username)
        if roles:
            await user_repo.apply_user_roles(
                session, user.id, org.id, add=[r.id for r in roles], remove=[], operator_id=ctx.user_id
            )
        h.summary = {
            "after": {
                **_snapshot(user),
                "org_name": org.name,
                "roles": [r.name for r in roles],
                "system_generated": generated is not None,  # 不含密码本身
            }
        }
        await event_service.publish_user_upserted(session, user)
        await session.commit()
        item = await _item_of(session, ctx, user)
        return UserCreated(user=item, initial_password=generated)


async def update_user(
    session: AsyncSession, ctx: AuthContext, request: Request, user_id: int, body: UserUpdate
) -> UserItem:
    async with oplog_scope(request, ctx, module="user", action="update", target_type="user", target_id=user_id) as h:
        user = await _get_manageable(session, ctx, user_id, for_update=True)
        h.set_target(user.id, user.username)
        _ensure_version(user, body.version)
        before = _snapshot(user)
        org_changed = body.org_id != user.org_id
        if org_changed:
            org = await _get_manageable_org(session, ctx, body.org_id)
            user.org_id = org.id
            user.company_id = org.company_id
            user.dept_id = org.id
        if (
            body.mobile
            and body.mobile != user.mobile
            and await user_repo.mobile_exists(session, body.mobile, exclude_id=user.id)
        ):
            raise BizError(*MOBILE_EXISTS)
        user.name = body.name
        user.mobile = body.mobile
        user.email = body.email
        user.version += 1
        user.updated_by = ctx.user_id
        await _flush_user(session)
        h.summary = {"before": before, "after": _snapshot(user)}
        await event_service.publish_user_upserted(session, user)
        await session.commit()
        if org_changed:  # 所属公司/部门变化会改变其数据范围
            await _invalidate_quietly(user.id)
        return await _item_of(session, ctx, user)


async def set_status(
    session: AsyncSession, ctx: AuthContext, request: Request, user_id: int, body: UserStatusBody
) -> UserItem:
    async with oplog_scope(request, ctx, module="user", action="status", target_type="user", target_id=user_id) as h:
        user = await _get_manageable(session, ctx, user_id, for_update=True)
        h.set_target(user.id, user.username)
        if user.id == ctx.user_id and body.status == Status.DISABLED.value:
            raise BizError(*USER_PROTECTED_SELF)
        if user.is_builtin and body.status == Status.DISABLED.value:
            raise BizError(*USER_PROTECTED_BUILTIN)
        _ensure_version(user, body.version)
        before = user.status
        h.summary = {"before": {"status": before}, "after": {"status": body.status}}
        if before == body.status:  # 未变化：不改动
            return await _item_of(session, ctx, user)

        user.status = body.status
        user.version += 1
        user.updated_by = ctx.user_id
        sids: list[str] = []
        if body.status == Status.DISABLED.value:
            sids = await session_service.revoke_all(session, user.id, RevokeReason.USER_DISABLED)
        await _flush_user(session)
        await event_service.publish_user_upserted(session, user)
        await session.commit()
        # 即时生效：先清会话缓存，再使权限上下文失效
        if body.status == Status.DISABLED.value:
            await _purge_quietly(user.id, sids)
        await _invalidate_quietly(user.id)
        return await _item_of(session, ctx, user)


async def reset_password(
    session: AsyncSession, ctx: AuthContext, request: Request, user_id: int, body: ResetPasswordBody
) -> PasswordReset:
    async with oplog_scope(
        request, ctx, module="user", action="reset_password", target_type="user", target_id=user_id
    ) as h:
        user = await _get_manageable(session, ctx, user_id, for_update=True)
        h.set_target(user.id, user.username)
        password_hash, generated = await _prepare_password(body.password)
        user.password_hash = password_hash
        user.must_change_password = True
        user.password_changed_at = None  # 重置后须由用户本人改密
        user.updated_by = ctx.user_id
        sids = await session_service.revoke_all(session, user.id, RevokeReason.PASSWORD_RESET)
        await _flush_user(session)
        h.summary = {"system_generated": generated is not None, "revoked_sessions": len(sids)}  # 不含密码本身
        await event_service.publish_user_upserted(session, user)
        await session.commit()
        await _purge_quietly(user.id, sids)
        await _invalidate_quietly(user.id)
        return PasswordReset(password=generated)


async def _lost_permissions(session: AsyncSession, ctx: AuthContext, final_roles: list[SysRole]) -> list[str]:
    """操作人修改自己的角色后，会失去的关键权限（超管不受影响）。"""
    if ctx.is_super_admin:
        return []
    enabled = [r for r in final_roles if r.status == Status.ENABLED]
    if any(r.builtin_key == "super_admin" for r in enabled):
        return []
    perms = await permission_repo.role_permission_codes(session, [r.id for r in enabled])
    after: set[str] = set().union(*perms.values()) if perms else set()
    return [c for c in _LOCKOUT_WATCH if ctx.has_perm(c) and c not in after]


async def assign_roles(
    session: AsyncSession, ctx: AuthContext, request: Request, user_id: int, body: AssignRolesBody
) -> UserItem:
    async with oplog_scope(
        request, ctx, module="user", action="assign_role", target_type="user", target_id=user_id
    ) as h:
        user = await _get_manageable(session, ctx, user_id, for_update=True)
        h.set_target(user.id, user.username)
        submitted = set(body.role_ids)
        await role_service.ensure_roles_assignable(session, ctx, submitted, user_id=user.id)

        # 最终集合 = 现有角色中操作人不可管理的（含停用角色、不可见/超范围角色）∪ 提交集合
        existing_ids = await role_repo.user_role_ids(session, user.id)
        assignable_ids = {r.id for r in await role_service.assignable_roles(session, ctx, user.company_id)}
        kept = existing_ids - assignable_ids
        final_ids = kept | submitted
        roles_map = {r.id: r for r in await role_repo.get_roles_by_ids(session, existing_ids | final_ids)}
        final_roles = [roles_map[i] for i in sorted(final_ids) if i in roles_map]

        if user.id == ctx.user_id and not body.confirm_self_lockout:
            lost = await _lost_permissions(session, ctx, final_roles)
            if lost:
                raise BizError(SELF_LOCKOUT[0], SELF_LOCKOUT[1], {"lost_permissions": lost})

        await user_repo.apply_user_roles(
            session,
            user.id,
            user.org_id,
            add=final_ids - existing_ids,
            remove=existing_ids - final_ids,
            operator_id=ctx.user_id,
        )
        h.summary = {
            "before": [roles_map[i].name for i in sorted(existing_ids) if i in roles_map],
            "after": [r.name for r in final_roles],
        }
        await session.commit()
        await _invalidate_quietly(user.id)
        return (await _to_items(session, ctx, [user]))[0]


async def delete_user(session: AsyncSession, ctx: AuthContext, request: Request, user_id: int) -> None:
    async with oplog_scope(request, ctx, module="user", action="delete", target_type="user", target_id=user_id) as h:
        user = await _get_manageable(session, ctx, user_id, for_update=True)
        h.set_target(user.id, user.username)
        if user.id == ctx.user_id:
            raise BizError(*USER_PROTECTED_SELF)
        if user.is_builtin:
            raise BizError(*USER_PROTECTED_BUILTIN)
        h.summary = {"before": _snapshot(user)}
        user.is_deleted = True
        user.version += 1
        user.updated_by = ctx.user_id
        sids = await session_service.revoke_all(session, user.id, RevokeReason.USER_DELETED)
        await _flush_user(session)
        await event_service.publish_user_upserted(session, user)
        await session.commit()
        await _purge_quietly(user.id, sids)
        await _invalidate_quietly(user.id)
