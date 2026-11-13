"""事件发布：统一信封 ``{"event_id","type","occurred_at","payload"}``，写入单字段 ``data``。"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from platform_common.events.streams import MESSAGE_FIELD, STREAM_MAXLEN
from platform_common.redis import get_redis

logger = logging.getLogger(__name__)

_PENDING_KEY = "kbp_pending_events"
_tasks: set[asyncio.Task[None]] = set()


def build_envelope(type_: str, payload: dict[str, Any], event_id: str | None = None) -> dict[str, Any]:
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "type": type_,
        "occurred_at": datetime.now(UTC).isoformat(),
        "payload": payload,
    }


async def publish(stream: str, type_: str, payload: dict[str, Any]) -> str:
    """XADD 并返回 event_id；失败抛出异常（调用方决定是否忽略）。"""
    envelope = build_envelope(type_, payload)
    await get_redis().xadd(
        stream,
        {MESSAGE_FIELD: json.dumps(envelope, ensure_ascii=False, default=str)},
        maxlen=STREAM_MAXLEN,
        approximate=True,
    )
    return str(envelope["event_id"])


async def _safe_publish(stream: str, type_: str, payload: dict[str, Any]) -> None:
    try:
        await publish(stream, type_, payload)
    except Exception:
        logger.error("提交后发布事件失败", exc_info=True, extra={"stream": stream, "type": type_})


def publish_after_commit(session: AsyncSession, stream: str, type_: str, payload: dict[str, Any]) -> None:
    """注册到 session.info，事务提交成功后才发布；回滚则丢弃；发布失败只记日志。"""
    session.sync_session.info.setdefault(_PENDING_KEY, []).append((stream, type_, payload))


@event.listens_for(Session, "after_commit")
def _flush_pending(session: Session) -> None:
    pending: list[tuple[str, str, dict[str, Any]]] = session.info.pop(_PENDING_KEY, [])
    if not pending:
        return
    loop = asyncio.get_running_loop()

    async def _run() -> None:
        for stream, type_, payload in pending:  # 保序
            await _safe_publish(stream, type_, payload)

    task = loop.create_task(_run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


@event.listens_for(Session, "after_rollback")
@event.listens_for(Session, "after_soft_rollback")
def _drop_pending(session: Session, *_: Any) -> None:
    session.info.pop(_PENDING_KEY, None)


async def drain_pending_publishes() -> None:
    """等待已调度的提交后发布完成（优雅停机与测试用）。"""
    if _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)
