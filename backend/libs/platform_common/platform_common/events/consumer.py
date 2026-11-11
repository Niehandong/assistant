"""Redis Streams 消费组封装：至少一次投递、崩溃恢复（XAUTOCLAIM）、重试、死信。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import socket
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from platform_common.events.streams import MESSAGE_FIELD, STREAM_DEAD, STREAM_MAXLEN
from platform_common.redis import get_redis

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class StreamConsumer:
    """消费组消费者。

    - 自动建组（MKSTREAM，从头消费）；handler 成功才 XACK。
    - handler 抛异常：消息保持 pending，在本消费者下一轮按退避重试；累计失败达到 ``max_retries`` 后
      写入 ``stream:dead`` 并 XACK。
    - 其他消费者崩溃遗留、空闲超过 ``claim_idle_ms`` 的消息由 XAUTOCLAIM 接管。
    - handler 收到的是解析后的信封 dict，额外带 ``_stream_id``；JSON 不合法的消息直接进死信。
    """

    def __init__(
        self,
        stream: str,
        group: str,
        handler: Handler,
        *,
        batch: int = 50,
        block_ms: int = 2000,  # 须小于 Redis 客户端读超时（5s），否则空闲时会被误判为超时
        claim_idle_ms: int = 600_000,
        max_retries: int = 5,
        consumer_name: str | None = None,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self.stream = stream
        self.group = group
        self.handler = handler
        self.batch = batch
        self.block_ms = block_ms
        self.claim_idle_ms = claim_idle_ms
        self.max_retries = max_retries
        self.consumer = consumer_name or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.retry_backoff_seconds = retry_backoff_seconds
        self._stop = asyncio.Event()
        self._failures: dict[str, int] = {}
        self._last_claim = 0.0

    async def _ensure_group(self) -> None:
        try:
            await get_redis().xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def run_forever(self) -> None:
        await self._ensure_group()
        logger.info("消费者启动", extra={"stream": self.stream, "group": self.group, "consumer": self.consumer})
        while not self._stop.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except RedisTimeoutError:
                # 阻塞读取期间无新消息导致的读超时属于正常空闲；Redis 真不可用会表现为连接错误并走下面的 ERROR
                logger.debug("消费循环读超时（空闲），继续", extra={"stream": self.stream})
            except Exception:
                logger.error("消费循环异常，稍后重试", exc_info=True, extra={"stream": self.stream})
                await self._sleep(1.0)
        logger.info("消费者已停止", extra={"stream": self.stream, "consumer": self.consumer})

    async def stop(self) -> None:
        """请求优雅停止：处理完当前批次后退出 run_forever。"""
        self._stop.set()

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)

    async def _tick(self) -> None:
        r = get_redis()
        # 1. 本消费者自己的 pending（失败待重试）
        mine = await r.xreadgroup(self.group, self.consumer, {self.stream: "0"}, count=self.batch)
        entries = self._entries(mine)
        if entries:
            await self._process(entries)
            await self._sleep(min(self.retry_backoff_seconds * (2 ** max(self._failures.values(), default=0)), 10))
            return
        # 2. 接管他人遗留的超时消息（限频：每 claim_idle_ms/4 且至少 1s 一次）
        now = asyncio.get_running_loop().time()
        if now - self._last_claim >= max(1.0, self.claim_idle_ms / 4000):
            self._last_claim = now
            _, claimed, *_ = await r.xautoclaim(
                self.stream,
                self.group,
                self.consumer,
                min_idle_time=self.claim_idle_ms,
                start_id="0-0",
                count=self.batch,
            )
            if claimed:
                await self._process([(mid, fields) for mid, fields in claimed if fields is not None])

        # 3. 新消息；与 stop 竞争，使停止不必等满 block_ms
        async def _read_new() -> Any:
            return await r.xreadgroup(
                self.group, self.consumer, {self.stream: ">"}, count=self.batch, block=self.block_ms
            )

        read: asyncio.Task[Any] = asyncio.create_task(_read_new())
        stopper = asyncio.create_task(self._stop.wait())
        done, _ = await asyncio.wait({read, stopper}, return_when=asyncio.FIRST_COMPLETED)
        if read not in done:
            read.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await read
            return
        stopper.cancel()
        await self._process(self._entries(read.result()))

    @staticmethod
    def _entries(resp: Any) -> list[tuple[str, dict[str, str]]]:
        out: list[tuple[str, dict[str, str]]] = []
        for _stream, messages in resp or []:
            out.extend((mid, fields) for mid, fields in messages if fields is not None)
        return out

    async def _process(self, entries: list[tuple[str, dict[str, str]]]) -> None:
        r = get_redis()
        for mid, fields in entries:
            try:
                body = json.loads(fields[MESSAGE_FIELD])
                if not isinstance(body, dict):
                    raise ValueError("消息体不是对象")
            except (KeyError, ValueError) as exc:
                await self._dead_letter(mid, fields, f"消息格式不合法: {exc}")
                continue
            try:
                await self.handler({**body, "_stream_id": mid})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                n = self._failures.get(mid, 0) + 1
                self._failures[mid] = n
                logger.error(
                    "消息处理失败", exc_info=True, extra={"stream": self.stream, "message_id": mid, "attempt": n}
                )
                if n >= self.max_retries:
                    await self._dead_letter(mid, fields, repr(exc))
                continue
            await r.xack(self.stream, self.group, mid)
            self._failures.pop(mid, None)

    async def _dead_letter(self, mid: str, fields: dict[str, str], error: str) -> None:
        r = get_redis()
        await r.xadd(
            STREAM_DEAD,
            {
                "stream": self.stream,
                "group": self.group,
                "message_id": mid,
                "error": error[:1000],
                "failed_at": datetime.now(UTC).isoformat(),
                MESSAGE_FIELD: fields.get(MESSAGE_FIELD, json.dumps(fields, ensure_ascii=False)),
            },
            maxlen=STREAM_MAXLEN,
            approximate=True,
        )
        await r.xack(self.stream, self.group, mid)
        self._failures.pop(mid, None)
        logger.error("消息进入死信", extra={"stream": self.stream, "message_id": mid, "error": error[:200]})
