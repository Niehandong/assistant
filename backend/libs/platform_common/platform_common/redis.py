"""Redis 连接池（进程内单例）。"""

from __future__ import annotations

from redis.asyncio import BlockingConnectionPool, ConnectionPool, Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError

from platform_common.config import BaseServiceSettings

_pool: ConnectionPool | None = None
_client: Redis | None = None


def init_redis(settings: BaseServiceSettings) -> Redis:
    global _pool, _client
    if _client is None:
        # 连接已被对端关闭（Redis 重启后池内旧连接）时自动重连重试，避免恢复后首个请求仍失败；
        # health_check_interval 让空闲连接在复用前先探活；Redis 真正不可用时重试很快耗尽并抛出。
        # 使用阻塞型连接池：连接用尽时排队等待（最长 REDIS_POOL_TIMEOUT_SECONDS），而不是立即抛 "Too many connections"
        _pool = BlockingConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            timeout=settings.REDIS_POOL_TIMEOUT_SECONDS,
            socket_timeout=5,
            socket_connect_timeout=3,
            health_check_interval=15,
            retry=Retry(ExponentialBackoff(cap=0.3, base=0.05), retries=2),
            retry_on_error=[RedisConnectionError],
        )
        _client = Redis(connection_pool=_pool)
    return _client


def get_redis() -> Redis:
    if _client is None:
        raise RuntimeError("Redis 尚未初始化，请先调用 init_redis(settings)")
    return _client


async def close_redis() -> None:
    global _pool, _client
    if _client is not None:
        await _client.aclose()
    if _pool is not None:
        await _pool.disconnect()
    _client = None
    _pool = None
