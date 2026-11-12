"""按密钥的每分钟限流（tech-design-m3 3.3 第 7 步）。

固定窗口：计数键 ``open:rl:{key_id}:{yyyyMMddHHmm}``（UTC 分钟），
``INCR`` 与 ``EXPIRE NX 120`` 在同一管道内一次往返发出，
多实例共享计数。窗口边界：每到整分钟切换新键，上一分钟的计数不影响下一分钟。
被拒绝的调用同样计入计数；``Retry-After`` = 距下一个整分钟的秒数，取值 1~60。
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.constants import OpenErrors
from platform_common.errors import BizError
from platform_common.redis import get_redis

WINDOW_TTL_SECONDS = 120


class RateLimitedError(BizError):
    """429601；``retry_after`` 供响应头 ``Retry-After``。"""

    def __init__(self, retry_after: int) -> None:
        super().__init__(*OpenErrors.RATE_LIMITED)
        self.retry_after = retry_after


def now_utc() -> datetime:
    """单独成函数，便于测试固定时间以验证窗口边界。"""
    return datetime.now(UTC)


def window_key(key_id: int, now: datetime) -> str:
    return f"open:rl:{key_id}:{now.astimezone(UTC):%Y%m%d%H%M}"


def retry_after_seconds(now: datetime) -> int:
    """到下一个整分钟的秒数（向上取整，至少 1，至多 60）。例：12:00:59.9 → 1；12:00:00.0 → 60。"""
    elapsed_us = now.second * 1_000_000 + now.microsecond
    remaining_us = 60_000_000 - elapsed_us
    return max(1, min(60, -(-remaining_us // 1_000_000)))


async def check(key_id: int, limit: int, *, now: datetime | None = None) -> None:
    """计数 +1；超过 ``limit`` 抛 ``RateLimitedError``。Redis 故障向上抛（全局映射为 503001）。"""
    moment = now or now_utc()
    pipe = get_redis().pipeline(transaction=False)  # 两条命令同一次写入、一次往返；无需 MULTI/EXEC
    pipe.incr(window_key(key_id, moment))
    pipe.expire(window_key(key_id, moment), WINDOW_TTL_SECONDS, nx=True)
    count = int((await pipe.execute())[0])
    if count > limit:
        raise RateLimitedError(retry_after_seconds(moment))
