"""API 密钥审计（BE-26，tech-design-m3 5.3）。

* 数据范围：密钥按 ``api_key.company_id / dept_id / created_by``，调用日志按 ``api_call_log`` 同名列，
  统一经共享库 ``data_scope_filter``；范围外的密钥一律 404000（防止 ID 越权）。
* 管理员只有"停用 / 删除"，没有编辑、启用、重新生成（AC-72）。
* ``can_view_unknown_calls`` 同时被 capabilities 与 call-logs 使用，保证"开关显示"与"开关生效"一致。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApiKey, OrgRef, UserRef
from app.repositories import api_key_repo, call_log_repo, ref_repo
from app.schemas.api_key import ApiKeyItem
from app.schemas.audit import AuditApiKeyItem, AuditCapabilities, AuditCreator, AuditOrgRef
from app.schemas.call_log import AuditCallLogItem, LogCreatorRef
from app.services import api_key_service, call_log_service, key_cache
from app.services.kb_client import get_kb_client
from platform_common.auth.context import AuthContext, load_auth_context
from platform_common.errors import BizError, CommonErrors
from platform_common.oplog import oplog_scope
from platform_common.pagination import PageParams
from platform_common.response import page

logger = logging.getLogger(__name__)


def can_view_unknown_calls(ctx: AuthContext) -> bool:
    """能否查看"无法识别密钥"的调用：超管，或任一启用角色数据范围为 ALL（集团管理员口径，无管辖根限制）。"""
    return ctx.is_super_admin or ctx.data_scope.all


def capabilities(ctx: AuthContext) -> AuditCapabilities:
    return AuditCapabilities(can_view_unknown_calls=can_view_unknown_calls(ctx))


# --------------------------------------------------------------------------- 组装


async def _owners(creator_ids: Sequence[int]) -> tuple[dict[int, AuthContext | None], dict[int, set[int]]]:
    """各创建人的权限上下文与 kb 可访问集合（上下文并发加载；可访问集合对全部创建人只调 kb 一次）。"""
    ids = sorted(set(creator_ids))
    if not ids:
        return {}, {}
    ctxs = await asyncio.gather(*(load_auth_context(i) for i in ids))
    accessible = await get_kb_client().accessible_datasets(ids)
    return dict(zip(ids, ctxs, strict=True)), {i: set(accessible.get(i, [])) for i in ids}


def _creator(uid: int, ref: UserRef | None) -> AuditCreator:
    if ref is None:
        return AuditCreator(id=uid, name="", username="", status="unknown")
    return AuditCreator(
        id=uid, name=ref.name, username=ref.username, status="deleted" if ref.is_deleted else ref.status
    )


def _org(oid: int, ref: OrgRef | None) -> AuditOrgRef:
    return AuditOrgRef(id=oid, name=ref.name if ref else "")


async def _build(
    session: AsyncSession,
    keys: Sequence[ApiKey],
    owner_ctxs: dict[int, AuthContext | None],
    accessible: dict[int, set[int]],
) -> list[AuditApiKeyItem]:
    base: list[ApiKeyItem] = await api_key_service.build_items_multi(session, owner_ctxs, keys, accessible)
    users = await ref_repo.users_by_ids(session, [k.created_by for k in keys])
    orgs = await ref_repo.orgs_by_ids(session, [i for k in keys for i in (k.company_id, k.dept_id)])
    out: list[AuditApiKeyItem] = []
    for k, it in zip(keys, base, strict=True):
        data = it.model_dump(exclude={"dataset_ids", "ip_whitelist"})
        out.append(
            AuditApiKeyItem(
                **data,
                creator=_creator(k.created_by, users.get(k.created_by)),
                company=_org(k.company_id, orgs.get(k.company_id)),
                dept=_org(k.dept_id, orgs.get(k.dept_id)),
            )
        )
    return out


# --------------------------------------------------------------------------- 密钥


async def list_keys(
    session: AsyncSession,
    ctx: AuthContext,
    params: PageParams,
    *,
    creator_keyword: str | None,
    org_id: int | None,
    status: str | None,
) -> dict[str, Any]:
    conds = api_key_repo.audit_conditions(
        ctx, creator_keyword=creator_keyword, org_id=org_id, status=status, now=datetime.now().astimezone()
    )
    keys, total = await api_key_repo.page_audit(session, conds, offset=params.offset, limit=params.limit)
    items: list[AuditApiKeyItem] = []
    if keys:
        owner_ctxs, accessible = await _owners([k.created_by for k in keys])
        items = await _build(session, keys, owner_ctxs, accessible)
    return page(items, total, params.page, params.page_size)


async def _require_in_scope(session: AsyncSession, ctx: AuthContext, key_id: int, *, lock: bool = False) -> ApiKey:
    key = await api_key_repo.get_in_scope(session, ctx, key_id, for_update=lock)
    if key is None:
        raise BizError(*CommonErrors.NOT_FOUND)
    return key


async def _item(session: AsyncSession, key: ApiKey) -> AuditApiKeyItem:
    owner_ctxs, accessible = await _owners([key.created_by])
    return (await _build(session, [key], owner_ctxs, accessible))[0]


async def disable_key(
    session: AsyncSession, ctx: AuthContext, request: Request, key_id: int, version: int
) -> AuditApiKeyItem:
    """enabled / disabled → admin_disabled；已是 admin_disabled 幂等成功（不校验 version、不写日志、version 不变）。"""
    async with oplog_scope(
        request, ctx, module="api_key", action="admin_disable", target_type="api_key", target_id=key_id
    ) as h:
        pre = await _require_in_scope(session, ctx, key_id)
        # 先于加锁取创建人上下文与可访问集合：iam/kb 不可用（503001）时尚未改库、不持有行锁
        owner_ctxs, accessible = await _owners([pre.created_by])
        key = await _require_in_scope(session, ctx, key_id, lock=True)
        h.set_target(key.id, key.name)
        if key.status == "admin_disabled":
            h.suppress = True
            return (await _build(session, [key], owner_ctxs, accessible))[0]
        if key.version != version:
            raise BizError(*CommonErrors.VERSION_CONFLICT)
        before = key.status
        key.status = "admin_disabled"
        key.admin_disabled_by = ctx.user_id
        key.admin_disabled_at = datetime.now().astimezone()
        key.version += 1
        key.updated_by = ctx.user_id
        await session.commit()
        await key_cache.invalidate(key.key_hash)
        h.summary = {
            "before": {"status": before},
            "after": {"status": "admin_disabled"},
            "creator_id": key.created_by,
            "key_prefix": key.key_prefix,
        }
        return (await _build(session, [key], owner_ctxs, accessible))[0]


async def delete_key(session: AsyncSession, ctx: AuthContext, request: Request, key_id: int) -> None:
    """任何存储状态都允许；逻辑删除。"""
    async with oplog_scope(
        request, ctx, module="api_key", action="admin_delete", target_type="api_key", target_id=key_id
    ) as h:
        key = await _require_in_scope(session, ctx, key_id, lock=True)
        h.set_target(key.id, key.name)
        h.summary = {"key_prefix": key.key_prefix, "creator_id": key.created_by, "stored_status": key.status}
        key.is_deleted = True
        key.version += 1
        key.updated_by = ctx.user_id
        await session.commit()
        await key_cache.invalidate(key.key_hash)


# --------------------------------------------------------------------------- 调用日志


async def list_call_logs(
    session: AsyncSession,
    ctx: AuthContext,
    params: PageParams,
    *,
    start_time: datetime | None,
    end_time: datetime | None,
    api_key_id: int | None,
    dataset_id: int | None,
    result: str | None,
    creator_keyword: str | None,
    include_unknown: bool,
) -> dict[str, Any]:
    start, end = call_log_service.resolve_time_range(start_time, end_time)
    f = call_log_repo.CallLogFilter(
        start_time=start,
        end_time=end,
        api_key_id=api_key_id,
        dataset_id=dataset_id,
        result=result,
        creator_keyword=creator_keyword,
        scope_ctx=ctx,
        # 无能力时静默忽略，不泄露是否存在此类记录
        include_unknown=include_unknown and can_view_unknown_calls(ctx),
    )
    rows, total = await call_log_repo.page_logs(session, f, offset=params.offset, limit=params.limit)
    users = await ref_repo.users_by_ids(session, [r.created_by for r in rows if r.created_by])
    items: list[AuditCallLogItem] = []
    for r in rows:
        ref = users.get(r.created_by)
        creator = LogCreatorRef(id=ref.id, name=ref.name) if ref is not None else None
        items.append(AuditCallLogItem(**call_log_service.to_item(r).model_dump(), creator=creator))
    return page(items, total, params.page, params.page_size)
