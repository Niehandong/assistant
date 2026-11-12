"""调用日志生产端（tech-design-m3 3.4）：开放检索每个出口恰好产生一条日志，XADD 到 ``stream:open.call_logs``。

* 不等待入库；XADD 失败只记错误日志，不影响响应。
* 无法识别密钥（第 1~2 步失败）的日志按 IP 采样：每 IP 每分钟最多 ``INVALID_KEY_LOG_PER_IP_PER_MIN`` 条。
* 调用方自带的 ``X-Request-Id`` 若已被使用过，日志里的 request_id 追加随机后缀以保证唯一（否则幂等键会吞掉日志）。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings, get_settings
from app.schemas.retrieve import CallLogPayload
from platform_common.events.publisher import publish
from platform_common.events.streams import STREAM_OPEN_CALL_LOGS
from platform_common.redis import get_redis

logger = logging.getLogger(__name__)

QUERY_LOG_MAX = 2000
RESULT_BY_CODE: dict[int, str] = {
    401601: "key_invalid",
    403601: "key_disabled",
    403602: "key_expired",
    403603: "ip_not_allowed",
    404601: "dataset_not_found",
    400001: "invalid_params",
    429601: "rate_limited",
    503601: "model_unavailable",
    503001: "service_unavailable",
    500000: "internal_error",
}
ERROR_TYPE_BY_CODE: dict[int, str] = {
    401601: "KEY_INVALID",
    403601: "KEY_DISABLED",
    403602: "KEY_EXPIRED",
    403603: "IP_NOT_ALLOWED",
    404601: "DATASET_NOT_FOUND",
    400001: "INVALID_PARAMS",
    429601: "RATE_LIMITED",
    503601: "MODEL_UNAVAILABLE",
    503001: "SERVICE_UNAVAILABLE",
    500000: "INTERNAL_ERROR",
}
OPEN_ERROR_CODES = frozenset(RESULT_BY_CODE)


@dataclass
class CallContext:
    """一次开放检索调用的日志上下文；随鉴权链推进逐步补全。"""

    request_id: str
    client_ip: str | None
    started: float = field(default_factory=time.perf_counter)
    called_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    client_supplied_id: bool = False
    api_key_id: int | None = None
    key_name: str | None = None
    key_prefix: str | None = None
    company_id: int | None = None
    dept_id: int | None = None
    created_by: int = 0
    dataset_id: int | None = None
    dataset_name: str | None = None
    query: str | None = None
    result_count: int = 0

    def latency_ms(self) -> int:
        return max(0, int((time.perf_counter() - self.started) * 1000))


def truncate_query(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.replace("\x00", "")[:QUERY_LOG_MAX]


async def _sample_unidentified(ip: str | None, settings: Settings) -> bool:
    """无法识别密钥的调用：同 IP 每分钟超过上限后不再记录（TQ-04）；Redis 故障时放行记录。"""
    limit = settings.INVALID_KEY_LOG_PER_IP_PER_MIN
    if limit <= 0:
        return False
    minute = datetime.now(UTC).strftime("%Y%m%d%H%M")
    key = f"open:invlog:{ip or 'unknown'}:{minute}"
    try:
        pipe = get_redis().pipeline(transaction=True)
        pipe.incr(key)
        pipe.expire(key, 120, nx=True)
        count = int((await pipe.execute())[0])
    except Exception:
        logger.warning("无效密钥日志采样计数失败，按放行处理", exc_info=True)
        return True
    return count <= limit


async def _unique_request_id(ctx: CallContext) -> str:
    """调用方自带的 X-Request-Id 只允许首次原样入库，重复使用时加后缀（仍可按前缀检索）。"""
    if not ctx.client_supplied_id:
        return ctx.request_id
    try:
        first = await get_redis().set(f"open:rid:{ctx.request_id}", "1", nx=True, ex=86400)
    except Exception:
        return ctx.request_id
    if first:
        return ctx.request_id
    return f"{ctx.request_id[:50]}~{uuid.uuid4().hex[:12]}"


async def record(ctx: CallContext, code: int, *, settings: Settings | None = None) -> bool:
    """写一条调用日志（``code=0`` 为成功）；返回是否已投递（被采样丢弃或失败为 False）。永不抛出。"""
    try:
        s = settings or get_settings()
        if ctx.api_key_id is None and not await _sample_unidentified(ctx.client_ip, s):
            return False
        result = "success" if code == 0 else RESULT_BY_CODE.get(code, "internal_error")
        payload = CallLogPayload(
            request_id=await _unique_request_id(ctx),
            api_key_id=ctx.api_key_id,
            key_name=ctx.key_name,
            key_prefix=ctx.key_prefix,
            company_id=ctx.company_id,
            dept_id=ctx.dept_id,
            dataset_id=ctx.dataset_id,
            dataset_name=ctx.dataset_name[:50] if ctx.dataset_name else None,
            query=ctx.query,
            result_count=ctx.result_count if code == 0 else 0,
            latency_ms=ctx.latency_ms(),
            result=result,  # type: ignore[arg-type]
            error_code=None if code == 0 else code,
            client_ip=ctx.client_ip[:64] if ctx.client_ip else None,
            called_at=ctx.called_at,
            created_by=ctx.created_by,
        )
        await publish(STREAM_OPEN_CALL_LOGS, "open.call_log", payload.model_dump(mode="json"))
        return True
    except Exception:
        logger.error("调用日志投递失败", exc_info=True, extra={"request_id": ctx.request_id, "code": code})
        return False
