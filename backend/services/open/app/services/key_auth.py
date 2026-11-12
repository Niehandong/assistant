"""开放检索鉴权链（tech-design-m3 3.3 第 1~6 步）。

第 7 步限流见 ``rate_limit``；参数校验、范围判定与 kb 调用见 ``retrieve_service``。
任何一步失败都抛 ``BizError``，并且在失败前已把已识别的密钥信息写进 ``CallContext``，保证日志记在密钥名下。
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network

from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.constants import OpenErrors
from app.core.security import hash_api_key, key_prefix_of
from app.repositories import api_key_repo
from app.services import key_cache
from app.services.call_log_writer import CallContext
from app.services.key_status import owner_available
from platform_common.auth.context import load_auth_context
from platform_common.db import get_session_factory
from platform_common.errors import BizError
from platform_common.redis import get_redis

logger = logging.getLogger(__name__)

_KEY_RE = re.compile(r"^kb-[0-9A-Za-z]{40}$")
_PREFIX_RE = re.compile(r"^kb-[0-9A-Za-z]{4}")


class KeyRecord(BaseModel):
    """缓存到 Redis 的密钥记录（只含鉴权所需字段，不含哈希与明文）。"""

    id: int
    name: str
    key_prefix: str
    created_by: int
    company_id: int
    dept_id: int
    scope_type: str
    status: str
    expires_at: datetime | None = None
    ip_whitelist: list[str] = []
    rate_limit_per_min: int
    dataset_ids: list[int] = []


def extract_bearer(authorization: str | None) -> str | None:
    """``Authorization: Bearer <key>``（scheme 不区分大小写）；缺失/格式不符 → None。"""
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def apply_key(ctx: CallContext, key: KeyRecord) -> None:
    ctx.api_key_id = key.id
    ctx.key_name = key.name
    ctx.key_prefix = key.key_prefix
    ctx.company_id = key.company_id
    ctx.dept_id = key.dept_id
    ctx.created_by = key.created_by


async def _load_record(key_hash: str, settings: Settings) -> KeyRecord | None:
    """Redis 缓存 → 库；不存在写负缓存 60 秒。"""
    redis = get_redis()
    cache_key = key_cache.cache_key(key_hash)
    raw = await redis.get(cache_key)
    if raw == key_cache.NULL_MARKER:
        return None
    if raw:
        try:
            return KeyRecord.model_validate_json(raw)
        except ValidationError:
            logger.warning("密钥缓存内容损坏，回源重建")
    async with get_session_factory()() as session:
        row = await api_key_repo.get_by_hash(session, key_hash)
        if row is None:
            await redis.set(cache_key, key_cache.NULL_MARKER, ex=key_cache.NULL_TTL_SECONDS)
            return None
        dataset_ids: list[int] = []
        if row.scope_type == "selected":
            dataset_ids = (await api_key_repo.dataset_ids_by_keys(session, [row.id])).get(row.id, [])
        record = KeyRecord(
            id=row.id,
            name=row.name,
            key_prefix=row.key_prefix,
            created_by=row.created_by,
            company_id=row.company_id,
            dept_id=row.dept_id,
            scope_type=row.scope_type,
            status=row.status,
            expires_at=row.expires_at,
            ip_whitelist=list(row.ip_whitelist or []),
            rate_limit_per_min=row.rate_limit_per_min,
            dataset_ids=dataset_ids,
        )
    await redis.set(cache_key, record.model_dump_json(), ex=settings.API_KEY_CACHE_SECONDS)
    return record


async def lookup_key(ctx: CallContext, authorization: str | None, settings: Settings | None = None) -> KeyRecord:
    """第 1~2 步：取出并识别密钥；失败 → 401601（日志 api_key_id 为空，前缀取请求中的前 7 位）。"""
    s = settings or get_settings()
    token = extract_bearer(authorization)
    if token is not None and _PREFIX_RE.match(token):
        ctx.key_prefix = key_prefix_of(token)
    if token is None or not _KEY_RE.match(token):
        raise BizError(*OpenErrors.KEY_INVALID)
    record = await _load_record(hash_api_key(token, s), s)
    if record is None:
        raise BizError(*OpenErrors.KEY_INVALID)
    apply_key(ctx, record)
    return record


def ip_allowed(client_ip: str | None, whitelist: list[str]) -> bool:
    """白名单为空 = 不限制；否则客户端 IP 须命中某条 IPv4 / CIDR（IPv4 映射的 IPv6 按 IPv4 比较）。"""
    if not whitelist:
        return True
    if not client_ip:
        return False
    try:
        addr: IPv4Address | IPv6Address = ip_address(client_ip)
    except ValueError:
        return False
    if isinstance(addr, IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    for entry in whitelist:
        try:
            net = ip_network(entry, strict=False)
        except ValueError:
            logger.error("密钥白名单含非法条目，已忽略", extra={"entry": entry})
            continue
        if addr.version == net.version and addr in net:
            return True
    return False


async def check_key(ctx: CallContext, key: KeyRecord, client_ip: str | None, *, now: datetime | None = None) -> None:
    """第 3~6 步：存储状态 → 创建人当前可用性 → 过期 → IP 白名单（先后顺序即错误优先级）。"""
    if key.status in ("disabled", "admin_disabled"):
        raise BizError(*OpenErrors.KEY_DISABLED)
    owner = await load_auth_context(key.created_by)  # iam 不可用 → 503001
    if not owner_available(owner):
        raise BizError(*OpenErrors.KEY_DISABLED)
    if key.expires_at is not None and key.expires_at <= (now or datetime.now(UTC)):
        raise BizError(*OpenErrors.KEY_EXPIRED)
    if not ip_allowed(client_ip, key.ip_whitelist):
        raise BizError(*OpenErrors.IP_NOT_ALLOWED)
