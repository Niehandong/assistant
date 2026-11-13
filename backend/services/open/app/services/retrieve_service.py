"""开放检索编排（tech-design-m3 3.3、5.4）。

``handle`` 是唯一入口：执行鉴权链 → 限流 → 参数校验 → 范围判定 → 调 kb，并在**唯一的出口**写一条调用日志，
同时把任何异常（含 Redis/数据库不可用、未预期异常）转换成带 ``error_type`` / ``request_id`` 的统一错误响应。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.core.config import Settings, get_settings
from app.core.constants import OpenErrors
from app.models import ApiKey
from app.schemas.retrieve import RetrieveData, RetrieveRequest, validation_errors
from app.services import key_auth, key_cache, rate_limit
from app.services.call_log_writer import (
    ERROR_TYPE_BY_CODE,
    OPEN_ERROR_CODES,
    CallContext,
    record,
    truncate_query,
)
from app.services.kb_client import get_kb_client
from platform_common.db import get_session_factory
from platform_common.errors import BizError, CommonErrors
from platform_common.redis import get_redis

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 64 * 1024
_DATASET_ID_RE = re.compile(r"^[0-9]{1,18}$")  # 仅 ASCII 数字，且不超过 BIGINT
_background: set[asyncio.Task[None]] = set()


@dataclass
class Inbound:
    """路由层收集的原始入参（服务层不依赖 Starlette Request）。"""

    request_id: str
    client_ip: str | None
    authorization: str | None
    dataset_id_raw: str
    read_body: Callable[[], Awaitable[bytes]]
    client_supplied_id: bool = False


@dataclass
class Outcome:
    status: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


class _InvalidParams(BizError):
    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__(*CommonErrors.INVALID_PARAMS, data={"errors": errors})


def error_body(code: int, message: str, request_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """统一错误响应体；``data`` 一定含 ``error_type`` 与 ``request_id``（未知错误码退化为 ``HTTP_<状态>``）。"""
    data: dict[str, Any] = {
        "error_type": ERROR_TYPE_BY_CODE.get(code, f"HTTP_{code // 1000}"),
        "request_id": request_id,
    }
    if extra:
        data.update({k: v for k, v in extra.items() if k not in data})
    return {"code": code, "message": message, "data": data}


def parse_dataset_id(raw: str) -> int | None:
    if not _DATASET_ID_RE.match(raw):
        return None
    value = int(raw)
    return value if 1 <= value < 2**63 else None


def _parse_json(raw: bytes) -> Any:
    """宽松解析：失败返回 ``_BAD``。"""
    try:
        return json.loads(raw)
    except ValueError:
        return _BAD


_BAD = object()


def _normalize(exc: Exception) -> BizError:
    """任意异常 → 开放检索 10 个错误码之一（不暴露细节）。"""
    if isinstance(exc, BizError):
        if exc.code in OPEN_ERROR_CODES:
            return exc
        logger.error("开放检索遇到非预期的业务错误码", extra={"code": exc.code, "msg_": exc.message})
        return BizError(*CommonErrors.INTERNAL)
    if isinstance(exc, RedisError | PoolTimeoutError | OperationalError | InterfaceError):
        logger.error("依赖不可用", exc_info=exc)
        return BizError(*CommonErrors.DEPENDENCY_UNAVAILABLE)
    if isinstance(exc, DBAPIError):
        logger.error("数据库异常", exc_info=exc)
        return BizError(*CommonErrors.INTERNAL)
    logger.error("开放检索未处理异常", exc_info=exc)
    return BizError(*CommonErrors.INTERNAL)


def _map_kb_error(exc: BizError) -> BizError:
    """kb 内部检索错误 → 开放错误：404000→404601；409303/503301→503601；400001→400001；不可达 503001 原样。"""
    if exc.code == 404000:
        return BizError(*OpenErrors.DATASET_NOT_FOUND)
    if exc.code in (409303, 503301):
        return BizError(*OpenErrors.MODEL_UNAVAILABLE)
    if exc.code == 400001:
        errors = exc.data.get("errors") if isinstance(exc.data, dict) else None
        return _InvalidParams(errors if isinstance(errors, list) else [])
    if exc.code == 503001:
        return exc
    logger.error("kb 内部检索返回非预期错误码", extra={"code": exc.code})
    return BizError(*CommonErrors.INTERNAL)


async def handle(inbound: Inbound, *, settings: Settings | None = None) -> Outcome:
    """执行一次开放检索并恰好写一条调用日志。永不抛出。"""
    s = settings or get_settings()
    ctx = CallContext(
        request_id=inbound.request_id,
        client_ip=inbound.client_ip,
        client_supplied_id=inbound.client_supplied_id,
        dataset_id=parse_dataset_id(inbound.dataset_id_raw),
    )
    try:
        data = await _execute(ctx, inbound, s)
    except Exception as exc:
        err = _normalize(exc)
        await record(ctx, err.code, settings=s)
        extra = err.data if isinstance(err.data, dict) else None
        headers: dict[str, str] = {}
        if isinstance(err, rate_limit.RateLimitedError):
            headers["Retry-After"] = str(err.retry_after)
        return Outcome(err.http_status, error_body(err.code, err.message, ctx.request_id, extra), headers)
    await record(ctx, 0, settings=s)
    return Outcome(200, {"code": 0, "message": "ok", "data": data})


async def _execute(ctx: CallContext, inbound: Inbound, s: Settings) -> dict[str, Any]:
    key = await key_auth.lookup_key(ctx, inbound.authorization, s)  # 1~2
    raw_body = await _read_body(inbound)
    parsed = _parse_json(raw_body) if raw_body is not None else _BAD
    if isinstance(parsed, dict):
        ctx.query = truncate_query(parsed.get("query"))
    await key_auth.check_key(ctx, key, inbound.client_ip)  # 3~6
    await rate_limit.check(key.id, key.rate_limit_per_min)  # 7
    body = _validate(ctx, inbound, raw_body, parsed)  # 8
    dataset_id = ctx.dataset_id
    assert dataset_id is not None
    if key.scope_type == "selected" and dataset_id not in set(key.dataset_ids):  # 9
        raise BizError(*OpenErrors.DATASET_NOT_FOUND)
    try:  # 10
        result = await get_kb_client().retrieve(dataset_id, key.created_by, body.query, body.overrides())
    except BizError as exc:
        raise _map_kb_error(exc) from exc
    try:
        result["request_id"] = ctx.request_id
        data = RetrieveData.model_validate(_with_dataset_on_records(result)).model_dump(mode="json")
    except (ValidationError, KeyError, TypeError) as exc:
        logger.error("kb 检索响应结构不符合约定", exc_info=exc)
        raise BizError(*CommonErrors.INTERNAL) from exc
    ctx.dataset_name = data["dataset"]["name"]
    ctx.result_count = len(data["records"])
    await _touch_last_used(key.id)
    return data


def _with_dataset_on_records(result: dict[str, Any]) -> dict[str, Any]:
    """kb 的 records 不含 dataset 字段（契约在每条记录上带 ``dataset``），由 open 用响应的 ``dataset`` 补齐。"""
    dataset = result["dataset"]
    records = [{**r, "dataset": r.get("dataset") or dataset} for r in result.get("records", [])]
    return {**result, "records": records}


async def _read_body(inbound: Inbound) -> bytes | None:
    """读取请求体；超过 ``MAX_BODY_BYTES`` 视为不合法（返回 None，校验阶段报 400001）。"""
    raw = await inbound.read_body()
    return raw if len(raw) <= MAX_BODY_BYTES else None


def _validate(ctx: CallContext, inbound: Inbound, raw_body: bytes | None, parsed: Any) -> RetrieveRequest:
    errors: list[dict[str, str]] = []
    if ctx.dataset_id is None:
        errors.append({"field": "dataset_id", "message": "必须为正整数"})
    if raw_body is None:
        errors.append({"field": "", "message": f"请求体不能超过 {MAX_BODY_BYTES // 1024}KB"})
    elif parsed is _BAD:
        errors.append({"field": "", "message": "请求体必须是合法的 JSON"})
    elif not isinstance(parsed, dict):
        errors.append({"field": "", "message": "请求体必须是 JSON 对象"})
    else:
        try:
            body = RetrieveRequest.model_validate(parsed)
        except ValidationError as exc:
            errors.extend(validation_errors(exc))
        else:
            if not errors:
                return body
    raise _InvalidParams(errors)


_last_touch: dict[int, float] = {}  # 进程内预过滤：60 秒内已处理过的密钥不再访问 Redis（热路径省一次往返）


async def _touch_last_used(key_id: int) -> None:
    """成功调用后每分钟最多更新一次 last_used_at（``SET NX EX 60`` 抢到才更新），异步执行不阻塞响应。"""
    now = time.monotonic()
    if now - _last_touch.get(key_id, -1e9) < 60:
        return
    if len(_last_touch) > 10000:  # 防止长期运行无限增长
        _last_touch.clear()
    _last_touch[key_id] = now
    try:
        if not await get_redis().set(key_cache.last_used_key(key_id), "1", nx=True, ex=60):
            return
    except Exception:
        logger.warning("last_used 节流键写入失败", exc_info=True)
        return
    task = asyncio.create_task(_update_last_used(key_id))
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _update_last_used(key_id: int) -> None:
    try:
        async with get_session_factory()() as session:
            await session.execute(
                update(ApiKey)
                .where(ApiKey.id == key_id)
                .values(last_used_at=datetime.now(UTC), updated_at=ApiKey.updated_at)
            )
            await session.commit()
    except Exception:
        logger.warning("更新 last_used_at 失败", exc_info=True, extra={"key_id": key_id})


async def drain_background() -> None:
    """等待异步更新完成（优雅停机与测试）。"""
    if _background:
        await asyncio.gather(*list(_background), return_exceptions=True)
