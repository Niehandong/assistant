"""我的 API 密钥（BE-25，tech-design-m3 5.1）。

写接口统一校验顺序：本人且未删除（404000）→ ``SELECT ... FOR UPDATE`` → 存储状态 ``admin_disabled``
（403604/403605）→ ``version``（409001）→ 业务校验。明文只出现在创建与重新生成的返回值里。
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.constants import MAX_IP_WHITELIST, MAX_SCOPE_DATASETS, OpenErrors
from app.models import ApiKey
from app.repositories import api_key_repo, call_log_repo
from app.schemas.api_key import (
    AccessibleDataset,
    ApiKeyBody,
    ApiKeyItem,
    ApiKeySecretResult,
    ApiKeyStatusBody,
    ApiKeyUpdateBody,
    KeyCount,
    VersionBody,
)
from app.services import key_cache, key_status
from app.services.kb_client import get_kb_client
from platform_common.auth.context import AuthContext
from platform_common.errors import BizError, CommonErrors
from platform_common.oplog import OpLogHandle, oplog_scope
from platform_common.response import page

logger = logging.getLogger(__name__)
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


# --------------------------------------------------------------------------- 校验与规范化


def normalize_ip_whitelist(raw: Iterable[str] | None) -> list[str]:
    """IPv4 / IPv4 CIDR → 规范化字符串（单 IP 不带 /32，CIDR 清零主机位），去重保序；>20 条或格式错误 → 400603。"""
    out: list[str] = []
    for item in raw or []:
        text = item.strip()
        if not text:
            continue
        try:
            if "/" in text:
                net = ipaddress.IPv4Network(text, strict=False)
                value = str(net.network_address) if net.prefixlen == 32 else str(net)
            else:
                value = str(ipaddress.IPv4Address(text))
        except ValueError as exc:
            raise BizError(*OpenErrors.IP_WHITELIST_INVALID) from exc
        if value not in out:
            out.append(value)
    if len(out) > MAX_IP_WHITELIST:
        raise BizError(*OpenErrors.IP_WHITELIST_INVALID)
    return out


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TZ)
    return value


def _invalid(field: str, message: str) -> BizError:
    code, msg = CommonErrors.INVALID_PARAMS
    return BizError(code, msg, {"errors": [{"field": field, "message": message}]})


def _scope_dataset_ids(body: ApiKeyBody) -> list[int]:
    """selected 模式：1~50 个去重后的知识库 ID；all 模式忽略 dataset_ids。"""
    if body.scope_type != "selected":
        return []
    ids = list(dict.fromkeys(body.dataset_ids or []))
    if not ids:
        raise _invalid("dataset_ids", "指定知识库模式至少选择 1 个知识库")
    if len(ids) > MAX_SCOPE_DATASETS:
        raise _invalid("dataset_ids", f"最多选择 {MAX_SCOPE_DATASETS} 个知识库")
    if any(i < 1 for i in ids):
        raise _invalid("dataset_ids", "知识库 ID 不合法")
    return ids


def _check_expires(expires_at: datetime | None) -> datetime | None:
    expires_at = _aware(expires_at)
    if expires_at is not None and expires_at <= datetime.now(UTC):
        raise BizError(*OpenErrors.EXPIRES_IN_PAST)
    return expires_at


def _check_in_range(dataset_ids: Sequence[int], accessible: set[int]) -> None:
    missing = [i for i in dataset_ids if i not in accessible]
    if missing:
        raise BizError(*OpenErrors.DATASETS_OUT_OF_RANGE, data={"dataset_ids": missing})


# --------------------------------------------------------------------------- 展示


async def _accessible_set(ctx: AuthContext) -> set[int]:
    """创建人当前可访问的知识库（kb 实时计算）。kb 不可用 → 503001。"""
    result = await get_kb_client().accessible_datasets([ctx.user_id])
    return set(result.get(ctx.user_id, []))


def effective_dataset_ids(key: ApiKey, selected: Sequence[int], accessible: set[int]) -> list[int]:
    """当前真正可检索的知识库 = 创建人可访问 ∩（selected 模式的指定集合）。"""
    if key.scope_type == "selected":
        return sorted(accessible.intersection(selected))
    return sorted(accessible)


async def build_items(
    session: AsyncSession, owner_ctx: AuthContext | None, keys: Sequence[ApiKey], accessible: set[int]
) -> list[ApiKeyItem]:
    """批量组装 ``ApiKeyItem``（数据集合、近 7 天统计各一次查询，无 N+1）。单一创建人（本人视图）。"""
    return await build_items_multi(
        session, {k.created_by: owner_ctx for k in keys}, keys, {k.created_by: accessible for k in keys}
    )


async def build_items_multi(
    session: AsyncSession,
    owner_ctxs: Mapping[int, AuthContext | None],
    keys: Sequence[ApiKey],
    accessible_by_owner: Mapping[int, set[int]],
) -> list[ApiKeyItem]:
    """同上，但每把密钥按其创建人（``created_by``）取上下文与可访问集合（审计视图，BE-26 复用）。"""
    key_ids = [k.id for k in keys]
    datasets = await api_key_repo.dataset_ids_by_keys(session, key_ids)
    stats = await call_log_repo.stats_7d(session, key_ids)
    items: list[ApiKeyItem] = []
    for k in keys:
        selected = datasets.get(k.id, []) if k.scope_type == "selected" else []
        count = len(effective_dataset_ids(k, selected, accessible_by_owner.get(k.created_by, set())))
        calls, failures = stats.get(k.id, (0, 0))
        items.append(
            ApiKeyItem(
                id=k.id,
                name=k.name,
                description=k.description,
                key_masked=security.mask_key(k.key_prefix),
                scope_type=k.scope_type,  # type: ignore[arg-type]
                dataset_ids=selected,
                accessible_dataset_count=count,
                status=key_status.compute(k.status, k.expires_at, owner_ctxs.get(k.created_by), count),
                stored_status=k.status,  # type: ignore[arg-type]
                expires_at=k.expires_at,
                ip_whitelist=list(k.ip_whitelist or []),
                rate_limit_per_min=k.rate_limit_per_min,
                calls_7d=calls,
                failures_7d=failures,
                last_used_at=k.last_used_at,
                created_at=k.created_at,
                version=k.version,
            )
        )
    return items


async def _item_of(session: AsyncSession, ctx: AuthContext, key: ApiKey, accessible: set[int]) -> ApiKeyItem:
    return (await build_items(session, ctx, [key], accessible))[0]


def _snapshot(key: ApiKey, dataset_ids: Sequence[int]) -> dict[str, Any]:
    return {
        "name": key.name,
        "description": key.description,
        "scope_type": key.scope_type,
        "dataset_ids": sorted(dataset_ids),
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "ip_whitelist": list(key.ip_whitelist or []),
        "rate_limit_per_min": key.rate_limit_per_min,
    }


# --------------------------------------------------------------------------- 读


async def _require_owned(session: AsyncSession, ctx: AuthContext, key_id: int, *, lock: bool = False) -> ApiKey:
    key = await api_key_repo.get_owned(session, key_id, ctx.user_id, for_update=lock)
    if key is None:
        raise BizError(*CommonErrors.NOT_FOUND)
    return key


async def list_keys(
    session: AsyncSession, ctx: AuthContext, *, page_no: int, page_size: int, name: str | None, status: str | None
) -> dict[str, Any]:
    """先取本人全部密钥（预计 < 100）、计算状态后再按状态过滤与分页。"""
    keys = await api_key_repo.list_owned(session, ctx.user_id, name)
    items: list[ApiKeyItem] = []
    if keys:
        items = await build_items(session, ctx, keys, await _accessible_set(ctx))
    if status:
        items = [i for i in items if i.status == status]
    start = (page_no - 1) * page_size
    return page(items[start : start + page_size], len(items), page_no, page_size)


async def get_key(session: AsyncSession, ctx: AuthContext, key_id: int) -> ApiKeyItem:
    key = await _require_owned(session, ctx, key_id)
    return await _item_of(session, ctx, key, await _accessible_set(ctx))


async def accessible_datasets(session: AsyncSession, ctx: AuthContext, key_id: int) -> list[AccessibleDataset]:
    """当前真正可检索的知识库名单（创建人可访问 ∩ 指定集合）。任何存储状态都允许查看。"""
    key = await _require_owned(session, ctx, key_id)
    selected = (await api_key_repo.dataset_ids_by_keys(session, [key.id])).get(key.id, [])
    ids = effective_dataset_ids(key, selected, await _accessible_set(ctx))
    names: dict[int, str] = {}
    client = get_kb_client()
    for i in range(0, len(ids), 500):
        for b in await client.datasets_brief(ids[i : i + 500]):
            if not b.get("is_deleted"):
                names[int(b["id"])] = str(b["name"])
    return [AccessibleDataset(id=i, name=names[i]) for i in ids if i in names]


# --------------------------------------------------------------------------- 写


def _apply_fields(key: ApiKey, body: ApiKeyBody, expires_at: datetime | None, ips: list[str]) -> None:
    key.name = body.name
    key.description = body.description or None
    key.scope_type = body.scope_type
    key.expires_at = expires_at
    key.ip_whitelist = ips
    key.rate_limit_per_min = body.rate_limit_per_min


async def _commit_unique(session: AsyncSession) -> None:
    """提交；并发下的重名由部分唯一索引兜底 → 409601。"""
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if "uq_api_key_owner_name" in str(exc.orig):
            raise BizError(*OpenErrors.KEY_NAME_EXISTS) from exc
        raise


async def create_key(session: AsyncSession, ctx: AuthContext, request: Request, body: ApiKeyBody) -> ApiKeySecretResult:
    async with oplog_scope(request, ctx, module="api_key", action="create", target_type="api_key") as h:
        dataset_ids = _scope_dataset_ids(body)
        ips = normalize_ip_whitelist(body.ip_whitelist)
        expires_at = _check_expires(body.expires_at)
        if await api_key_repo.name_exists(session, ctx.user_id, body.name):
            raise BizError(*OpenErrors.KEY_NAME_EXISTS)
        accessible = await _accessible_set(ctx)
        _check_in_range(dataset_ids, accessible)

        plain = security.generate_api_key()
        key = ApiKey(
            key_prefix=security.key_prefix_of(plain),
            key_hash=security.hash_api_key(plain),
            company_id=ctx.company_id,
            dept_id=ctx.org_id,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
        )
        _apply_fields(key, body, expires_at, ips)
        session.add(key)
        await session.flush()
        if dataset_ids:
            await api_key_repo.replace_datasets(session, key.id, dataset_ids, ctx.user_id)
        await _commit_unique(session)
        h.set_target(key.id, key.name)
        h.summary = {"after": _snapshot(key, dataset_ids), "key_prefix": key.key_prefix}  # 不含明文
        item = await _item_of(session, ctx, key, accessible)
    return ApiKeySecretResult(api_key=plain, item=item)


async def _lock_for_write(
    session: AsyncSession, ctx: AuthContext, key_id: int, version: int, denied: tuple[int, str]
) -> ApiKey:
    """写接口前置校验链：本人（404000）→ FOR UPDATE → admin_disabled（denied）→ version（409001）。

    调用方应先 ``_require_owned`` 做无锁的归属预检（404000 优先于调 kb 可能产生的 503001）。
    """
    key = await _require_owned(session, ctx, key_id, lock=True)
    if key.status == "admin_disabled":
        raise BizError(*denied)
    if key.version != version:
        raise BizError(*CommonErrors.VERSION_CONFLICT)
    return key


async def update_key(
    session: AsyncSession, ctx: AuthContext, request: Request, key_id: int, body: ApiKeyUpdateBody
) -> ApiKeyItem:
    async with oplog_scope(
        request, ctx, module="api_key", action="update", target_type="api_key", target_id=key_id
    ) as h:
        await _require_owned(session, ctx, key_id)
        accessible = await _accessible_set(ctx)  # 先于加锁：kb 不可用时不持有行锁
        key = await _lock_for_write(session, ctx, key_id, body.version, OpenErrors.ADMIN_DISABLED_NO_MODIFY)
        h.set_target(key.id, key.name)
        dataset_ids = _scope_dataset_ids(body)
        ips = normalize_ip_whitelist(body.ip_whitelist)
        # 已过期的密钥可以只改其他字段：过期时间未变化时不重复校验（延长过期时间仍须晚于当前时间）
        new_expires = _aware(body.expires_at)
        expires_at = new_expires if new_expires == key.expires_at else _check_expires(new_expires)
        if key.name != body.name and await api_key_repo.name_exists(session, ctx.user_id, body.name, exclude_id=key.id):
            raise BizError(*OpenErrors.KEY_NAME_EXISTS)
        old_datasets = (await api_key_repo.dataset_ids_by_keys(session, [key.id])).get(key.id, [])
        # 只校验新增的知识库：已选但当前失去权限的保持原样（范围上限由检索时实时判定）
        _check_in_range([i for i in dataset_ids if i not in old_datasets], accessible)

        before = _snapshot(key, old_datasets)
        _apply_fields(key, body, expires_at, ips)
        key.version += 1
        key.updated_by = ctx.user_id
        await api_key_repo.replace_datasets(session, key.id, dataset_ids, ctx.user_id)
        await _commit_unique(session)
        after = _snapshot(key, dataset_ids)
        changed = [f for f in after if after[f] != before[f]]
        h.summary = {"before": {f: before[f] for f in changed}, "after": {f: after[f] for f in changed}}
        await key_cache.invalidate(key.key_hash)
        return await _item_of(session, ctx, key, accessible)


async def set_status(
    session: AsyncSession, ctx: AuthContext, request: Request, key_id: int, body: ApiKeyStatusBody
) -> ApiKeyItem:
    async with oplog_scope(
        request, ctx, module="api_key", action="status", target_type="api_key", target_id=key_id
    ) as h:
        await _require_owned(session, ctx, key_id)
        accessible = await _accessible_set(ctx)
        key = await _lock_for_write(session, ctx, key_id, body.version, OpenErrors.ADMIN_DISABLED_NO_TOGGLE)
        h.set_target(key.id, key.name)
        if key.status == body.status:  # 同值幂等：不写日志、version 不变
            h.suppress = True
            return await _item_of(session, ctx, key, accessible)
        h.summary = {"before": {"status": key.status}, "after": {"status": body.status}}
        key.status = body.status
        key.version += 1
        key.updated_by = ctx.user_id
        await session.commit()
        await key_cache.invalidate(key.key_hash)
        return await _item_of(session, ctx, key, accessible)


async def regenerate(
    session: AsyncSession, ctx: AuthContext, request: Request, key_id: int, body: VersionBody
) -> ApiKeySecretResult:
    async with oplog_scope(
        request, ctx, module="api_key", action="regenerate", target_type="api_key", target_id=key_id
    ) as h:
        await _require_owned(session, ctx, key_id)
        accessible = await _accessible_set(ctx)
        key = await _lock_for_write(session, ctx, key_id, body.version, OpenErrors.ADMIN_DISABLED_NO_MODIFY)
        h.set_target(key.id, key.name)
        old_hash, old_prefix = key.key_hash, key.key_prefix
        plain = security.generate_api_key()
        key.key_hash = security.hash_api_key(plain)
        key.key_prefix = security.key_prefix_of(plain)
        key.version += 1
        key.updated_by = ctx.user_id
        await session.commit()
        await key_cache.invalidate(old_hash)  # 旧值立即失效
        h.summary = {"before": {"key_prefix": old_prefix}, "after": {"key_prefix": key.key_prefix}}  # 不含明文
        item = await _item_of(session, ctx, key, accessible)
    return ApiKeySecretResult(api_key=plain, item=item)


async def delete_key(session: AsyncSession, ctx: AuthContext, request: Request, key_id: int) -> None:
    """任何存储状态都允许（含 admin_disabled）；逻辑删除。"""
    async with oplog_scope(
        request, ctx, module="api_key", action="delete", target_type="api_key", target_id=key_id
    ) as h:
        key = await _require_owned(session, ctx, key_id, lock=True)
        _summarize_delete(h, key)
        key.is_deleted = True
        key.version += 1
        key.updated_by = ctx.user_id
        await session.commit()
        await key_cache.invalidate(key.key_hash)


def _summarize_delete(h: OpLogHandle, key: ApiKey) -> None:
    h.set_target(key.id, key.name)
    h.summary = {"key_prefix": key.key_prefix}
    if key.status == "admin_disabled":
        h.summary["stored_status"] = "admin_disabled"  # 便于审计追溯


async def count_for_user(session: AsyncSession, user_id: int) -> KeyCount:
    return KeyCount(count=await api_key_repo.count_owned(session, user_id))
