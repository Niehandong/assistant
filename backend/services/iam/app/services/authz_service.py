"""权限上下文（AuthContext）计算与缓存、失效，以及 /auth/me 的权限码与菜单树组装。

BE-05 / 其他 service 的调用入口（签名见各函数）：

* ``await get_context(session, user_id) -> AuthContext | None``：计算并回写缓存（用户物理不存在返回 None）。
* ``await get_contexts(session, user_ids) -> dict[int, AuthContext | None]``：批量版本，无 N+1。
* ``await invalidate_user(user_id) -> None`` / ``invalidate_users(user_ids)``：``DEL authz:ctx:{uid}``。
* ``await bump_epoch() -> int``：``INCR authz:epoch``，使全部上下文在下次请求时重算。
* ``invalidate_user_after_commit(session, user_id)`` / ``bump_epoch_after_commit(session)``：
  注册到会话，事务提交成功后自动执行（回滚丢弃）。需要确定性时序时，也可在 ``await session.commit()`` 之后
  直接 ``await invalidate_user(...)``（推荐）。
* ``await get_me_payload(session, ctx) -> tuple[list[str], list[MenuNode]]``：``/auth/me`` 的 permissions 与 menus。
* ``build_menu_tree(permissions, owned_codes) -> list[MenuNode]``：纯函数，便于单测。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Collection, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from redis.exceptions import RedisError
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import BuiltinRole, DataScopeType, PermType, Status
from app.models import SysOrg, SysPermission, SysUser
from app.repositories import org_repo, permission_repo, role_repo, user_repo
from app.schemas.permission import MenuNode
from platform_common.auth import cache_keys, runtime
from platform_common.auth.context import AuthContext, DataScope
from platform_common.db import get_session_factory
from platform_common.errors import BizError, CommonErrors
from platform_common.redis import get_redis

logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo("Asia/Shanghai")
_AFTER_COMMIT_KEY = "iam_authz_after_commit"
_tasks: set[asyncio.Task[None]] = set()


# --------------------------------------------------------------------------- 失效


async def current_epoch() -> int:
    """当前 epoch；Redis 不可用 → 503001（无法判定上下文是否过期，不能放行）。"""
    try:
        return int(await get_redis().get(cache_keys.AUTHZ_EPOCH) or 0)
    except (RedisError, OSError) as exc:
        logger.error("读取 authz:epoch 失败", exc_info=True)
        raise BizError(*CommonErrors.DEPENDENCY_UNAVAILABLE) from exc


async def invalidate_user(user_id: int) -> None:
    await get_redis().delete(cache_keys.authz_context(user_id))


async def invalidate_users(user_ids: Collection[int]) -> None:
    if user_ids:
        await get_redis().delete(*[cache_keys.authz_context(u) for u in user_ids])


async def bump_epoch() -> int:
    return int(await get_redis().incr(cache_keys.AUTHZ_EPOCH))


def _after_commit(session: AsyncSession, func: Any, *args: Any) -> None:
    session.sync_session.info.setdefault(_AFTER_COMMIT_KEY, []).append((func, args))


def invalidate_user_after_commit(session: AsyncSession, user_id: int) -> None:
    _after_commit(session, invalidate_user, user_id)


def invalidate_users_after_commit(session: AsyncSession, user_ids: Collection[int]) -> None:
    _after_commit(session, invalidate_users, list(user_ids))


def bump_epoch_after_commit(session: AsyncSession) -> None:
    _after_commit(session, bump_epoch)


@event.listens_for(Session, "after_commit")
def _run_after_commit(session: Session) -> None:
    pending: list[tuple[Any, tuple[Any, ...]]] = session.info.pop(_AFTER_COMMIT_KEY, [])
    if not pending:
        return

    async def _run() -> None:
        for func, args in pending:
            try:
                await func(*args)
            except Exception:
                logger.error("提交后缓存失效失败", exc_info=True, extra={"func": getattr(func, "__name__", "?")})

    task = asyncio.get_running_loop().create_task(_run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


@event.listens_for(Session, "after_rollback")
@event.listens_for(Session, "after_soft_rollback")
def _drop_after_commit(session: Session, *_: Any) -> None:
    session.info.pop(_AFTER_COMMIT_KEY, None)


async def drain_after_commit() -> None:
    """等待已调度的提交后任务完成（停机与测试用）。"""
    if _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


# --------------------------------------------------------------------------- 计算


def _org_path(org: SysOrg | None, org_id: int) -> list[int]:
    if org is None:
        return [org_id]
    ancestors = [int(x) for x in org.ancestors.split(",") if x and x != "0"]
    return [*ancestors, org.id]


def _org_chain_enabled(path: Sequence[int], orgs: dict[int, SysOrg]) -> bool:
    for oid in path:
        o = orgs.get(oid)
        if o is None or o.is_deleted or o.status != Status.ENABLED:
            return False
    return True


async def compute_contexts(
    session: AsyncSession, user_ids: Collection[int], *, epoch: int
) -> dict[int, AuthContext | None]:
    """批量计算 AuthContext（不写缓存）。用户物理不存在 → None。

    规则（5.6.1 + 总体方案 3.6）：仅启用且未删除的角色生效；超管 = 持有启用的 super_admin 内置角色；
    permissions 为角色权限并集（超管 = 全部权限码）；已删除用户 permissions=[]、数据范围为空。
    """
    ids = list(dict.fromkeys(user_ids))
    users = await user_repo.get_by_ids(session, ids)
    if not users:
        return {uid: None for uid in ids}

    user_orgs = await org_repo.get_by_ids(session, {u.org_id for u in users.values()})
    path_ids: set[int] = set()
    for u in users.values():
        path_ids.update(_org_path(user_orgs.get(u.org_id), u.org_id))
    orgs = {**user_orgs, **await org_repo.get_by_ids(session, path_ids - user_orgs.keys())}

    live_ids = [uid for uid, u in users.items() if not u.is_deleted]
    roles = await role_repo.effective_roles_of_users(session, live_ids)
    role_ids = {r.role_id for r in roles}
    perms_by_role = await permission_repo.role_permission_codes(session, role_ids)
    custom_orgs = await role_repo.role_custom_orgs(session, {r.role_id for r in roles if r.data_scope == "CUSTOM"})
    all_codes: list[str] | None = None
    if any(r.builtin_key == BuiltinRole.SUPER_ADMIN for r in roles):
        all_codes = await permission_repo.list_all_codes(session)

    company_cache: dict[int, list[int]] = {}
    dept_cache: dict[tuple[int, int], list[int]] = {}
    roles_by_user: dict[int, list[role_repo.EffectiveRole]] = {}
    for r in roles:
        roles_by_user.setdefault(r.user_id, []).append(r)

    now = datetime.now(_LOCAL_TZ)
    result: dict[int, AuthContext | None] = {}
    for uid in ids:
        user = users.get(uid)
        if user is None:
            result[uid] = None
            continue
        path = _org_path(orgs.get(user.org_id), user.org_id)
        user_roles = roles_by_user.get(uid, [])
        is_super = any(r.builtin_key == BuiltinRole.SUPER_ADMIN for r in user_roles)

        scope = DataScope()
        company_ids: set[int] = set()
        org_ids: set[int] = set()
        for r in user_roles:
            kind = r.data_scope
            if kind == DataScopeType.ALL:
                scope.all = True
            elif kind == DataScopeType.COMPANY:
                company_ids.add(user.company_id)
            elif kind == DataScopeType.COMPANY_AND_CHILD:
                if user.company_id not in company_cache:
                    company_cache[user.company_id] = await org_repo.descendant_company_ids(session, user.company_id)
                company_ids.add(user.company_id)
                company_ids.update(company_cache[user.company_id])
            elif kind == DataScopeType.DEPT:
                org_ids.add(user.org_id)
            elif kind == DataScopeType.DEPT_AND_CHILD:
                key = (user.org_id, user.company_id)
                if key not in dept_cache:
                    dept_cache[key] = await org_repo.descendant_dept_ids(session, user.org_id, user.company_id)
                org_ids.add(user.org_id)
                org_ids.update(dept_cache[key])
            elif kind == DataScopeType.SELF:
                scope.include_self = True
            elif kind == DataScopeType.CUSTOM:
                org_ids.update(custom_orgs.get(r.role_id, set()))
        if is_super:
            scope.all = True
        scope.company_ids = sorted(company_ids)
        scope.org_ids = sorted(org_ids)

        if user.is_deleted:
            permissions: list[str] = []
        elif is_super:
            permissions = list(all_codes or [])
        else:
            codes: set[str] = set()
            for r in user_roles:
                codes |= perms_by_role.get(r.role_id, set())
            permissions = sorted(codes)

        result[uid] = AuthContext(
            user_id=user.id,
            username=user.username,
            name=user.name,
            status=Status(user.status).value,
            is_deleted=user.is_deleted,
            org_enabled=_org_chain_enabled(path, orgs),
            org_id=user.org_id,
            company_id=user.company_id,
            org_path=path,
            is_super_admin=is_super and not user.is_deleted,
            must_change_password=user.must_change_password,
            permissions=permissions,
            data_scope=scope if not user.is_deleted else DataScope(),
            epoch=epoch,
            computed_at=now,
        )
    return result


async def _write_cache(contexts: Collection[AuthContext]) -> None:
    ttl = get_settings().AUTHZ_CTX_TTL_SECONDS
    try:
        pipe = get_redis().pipeline()
        for ctx in contexts:
            pipe.set(cache_keys.authz_context(ctx.user_id), ctx.model_dump_json(), ex=ttl)
        await pipe.execute()
    except Exception:
        logger.warning("authz 上下文写缓存失败（忽略，下次请求回源重算）", exc_info=True)


async def get_contexts(session: AsyncSession, user_ids: Collection[int]) -> dict[int, AuthContext | None]:
    """批量计算并回写缓存。先读 epoch 再计算：计算期间若 epoch 被 bump，缓存内的旧 epoch 会使其自动失效。"""
    epoch = await current_epoch()
    result = await compute_contexts(session, user_ids, epoch=epoch)
    await _write_cache([c for c in result.values() if c is not None])
    return result


async def get_context(session: AsyncSession, user_id: int) -> AuthContext | None:
    return (await get_contexts(session, [user_id])).get(user_id)


# --------------------------------------------------------------------------- /auth/me


def build_menu_tree(permissions: Sequence[SysPermission], owned_codes: Collection[str] | None) -> list[MenuNode]:
    """组装菜单树。

    * ``owned_codes=None`` 表示全部菜单（超级管理员）。
    * 叶子菜单（无菜单类子节点）：拥有才出现；目录节点：其下出现任一子菜单即出现（无论是否直接拥有）。
    * 只含 ``perm_type=menu``；同级按 (sort_order, id) 升序。
    """
    menus = [p for p in permissions if p.perm_type == PermType.MENU]
    children_of: dict[int, list[SysPermission]] = {}
    for p in menus:
        children_of.setdefault(p.parent_id, []).append(p)
    owned = None if owned_codes is None else set(owned_codes)

    def build(parent_id: int) -> list[MenuNode]:
        nodes: list[MenuNode] = []
        for p in sorted(children_of.get(parent_id, []), key=lambda x: (x.sort_order, x.id)):
            kids = build(p.id)
            is_leaf = p.id not in children_of
            if (is_leaf and (owned is None or p.code in owned)) or kids:
                nodes.append(
                    MenuNode(code=p.code, name=p.name, path=p.path, icon=p.icon, sort_order=p.sort_order, children=kids)
                )
        return nodes

    return build(0)


async def get_me_payload(session: AsyncSession, ctx: AuthContext) -> tuple[list[str], list[MenuNode]]:
    """返回 (permissions, menus)。超管：全部权限码与全部菜单（ctx.permissions 已为全部码）。"""
    permissions = await permission_repo.list_all(session)
    owned = None if ctx.is_super_admin else ctx.permissions
    return list(ctx.permissions), build_menu_tree(permissions, owned)


async def user_exists(session: AsyncSession, user_id: int) -> SysUser | None:
    return (await user_repo.get_by_ids(session, [user_id])).get(user_id)


def run_after_commit(session: AsyncSession, func: Any, *args: Any) -> None:
    """通用的"提交成功后执行"注册入口（回滚丢弃）；供 session_service 等复用。"""
    _after_commit(session, func, *args)


# --------------------------------------------------------------------------- 本地 loader


async def load_context_locally(user_id: int) -> AuthContext | None:
    """iam 自身的上下文加载器：用独立会话直接计算并回写缓存，不经 HTTP 回调自己的内部接口。"""
    async with get_session_factory()() as session:
        return await get_context(session, user_id)


@asynccontextmanager
async def lifespan_hook(_app: FastAPI) -> AsyncIterator[None]:
    """启动时向共享库注册本地 loader，退出时恢复默认。"""
    runtime.set_context_loader(load_context_locally)
    try:
        yield
    finally:
        runtime.set_context_loader(None)
