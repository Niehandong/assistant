"""iam 只读副本同步（open 版，同 kb 实现方式；tech-design-m3 第 2 节）：事件消费 + 启动全量 + 定时增量对账。

* 事件：``StreamConsumer(stream:iam.events, group=open-ref-sync)``；
  按 ``updated_at`` 只接受更新的数据（幂等、容忍乱序）。
* 启动：副本为空（或无游标）则从头全量拉取 ``/internal/v1/sync/users|orgs``，
  之后每 ``REF_RECONCILE_INTERVAL_SECONDS`` 增量对账。
* 游标：Redis ``open:ref:cursor:users|orgs``，保存已见到的最大 ``(updated_at, id)``；每次对账回退 60 秒重叠（幂等）。
* 分页：首次不传 ``updated_after``，翻页时把上一页返回的 ``next`` 原样传回。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, Literal

from app.core.config import Settings, get_settings
from app.repositories import ref_repo
from app.schemas.ref_sync import OrgRefPayload, UserRefPayload
from platform_common.auth import runtime
from platform_common.db import get_session_factory
from platform_common.events.consumer import StreamConsumer
from platform_common.events.streams import STREAM_IAM_EVENTS
from platform_common.jobs import run_periodic
from platform_common.redis import get_redis

logger = logging.getLogger(__name__)

Kind = Literal["users", "orgs"]
GROUP = "open-ref-sync"
PAGE_LIMIT = 1000
CURSOR_OVERLAP = timedelta(seconds=60)
USER_UPSERTED = "user.upserted"
ORG_UPSERTED = "org.upserted"


def cursor_key(kind: Kind) -> str:
    return f"open:ref:cursor:{kind}"


# --------------------------------------------------------------------------- 应用（事件与拉取共用）


async def apply_users(items: list[UserRefPayload]) -> list[int]:
    async with get_session_factory()() as session:
        applied = await ref_repo.upsert_users(session, items)
        await session.commit()
    return applied


async def apply_orgs(items: list[OrgRefPayload]) -> list[int]:
    async with get_session_factory()() as session:
        applied = await ref_repo.upsert_orgs(session, items)
        await session.commit()
    return applied


async def handle_event(envelope: dict[str, Any]) -> None:
    """处理 stream:iam.events 的一条消息。载荷不合法时抛异常（由消费者重试后进死信）；未知类型忽略。"""
    type_ = envelope.get("type")
    payload = envelope.get("payload")
    if type_ == USER_UPSERTED:
        await apply_users([UserRefPayload.model_validate(payload)])
    elif type_ == ORG_UPSERTED:
        await apply_orgs([OrgRefPayload.model_validate(payload)])
    else:
        logger.debug("忽略未知 iam 事件", extra={"event_type": type_})


# --------------------------------------------------------------------------- 拉取与对账


async def _fetch_page(kind: Kind, params: dict[str, Any]) -> dict[str, Any]:
    data = await runtime.get_iam_client().get(f"/internal/v1/sync/{kind}", params=params)
    if not isinstance(data, dict):
        raise RuntimeError("iam 同步接口返回格式不合法")
    return data


async def _load_cursor(kind: Kind) -> dict[str, Any] | None:
    raw = await get_redis().get(cursor_key(kind))
    if not raw:
        return None
    try:
        value = json.loads(raw)
        datetime.fromisoformat(value["updated_after"])
        int(value["after_id"])
        return dict(value)
    except (ValueError, KeyError, TypeError):
        logger.warning("同步游标损坏，将全量拉取", extra={"kind": kind})
        return None


async def _save_cursor(kind: Kind, cursor: dict[str, Any]) -> None:
    await get_redis().set(cursor_key(kind), json.dumps(cursor))


async def sync_kind(kind: Kind, *, full: bool, page_limit: int = PAGE_LIMIT) -> int:
    """拉取并应用一种引用数据，返回处理的行数。

    ``full=True`` 从头开始；否则从游标回退 60 秒（无游标时同样从头）。每页应用后即推进游标，
    中途失败下次从已保存的游标继续（重叠区间幂等）。
    """
    params: dict[str, Any] = {"limit": page_limit}
    high: dict[str, Any] | None = None
    if not full and (cur := await _load_cursor(kind)) is not None:
        start = datetime.fromisoformat(cur["updated_after"]) - CURSOR_OVERLAP
        params.update(updated_after=start.isoformat(), after_id=0)
        high = cur
    total = 0
    while True:
        data = await _fetch_page(kind, params)
        items = data.get("items") or []
        if items:
            if kind == "users":
                await apply_users([UserRefPayload.model_validate(i) for i in items])
            else:
                await apply_orgs([OrgRefPayload.model_validate(i) for i in items])
            total += len(items)
            last = items[-1]
            cand = {"updated_after": last["updated_at"], "after_id": int(last["id"])}
            if high is None or _cursor_gt(cand, high):
                high = cand
                await _save_cursor(kind, high)
        nxt = data.get("next")
        if not nxt:
            return total
        params = {"limit": page_limit, "updated_after": nxt["updated_after"], "after_id": nxt["after_id"]}


def _cursor_gt(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ta, tb = datetime.fromisoformat(a["updated_after"]), datetime.fromisoformat(b["updated_after"])
    return (ta, a["after_id"]) > (tb, b["after_id"])


async def initial_sync() -> None:
    """启动时：副本为空则全量拉取。"""
    async with get_session_factory()() as session:
        empty = {"users": await ref_repo.count_users(session) == 0, "orgs": await ref_repo.count_orgs(session) == 0}
    for kind in ("orgs", "users"):  # 先组织后用户
        if empty[kind]:
            n = await sync_kind(kind, full=True)
            logger.info("副本全量同步完成", extra={"kind": kind, "rows": n})


async def reconcile() -> None:
    """增量对账（游标回退 60 秒重叠）。"""
    for kind in ("orgs", "users"):
        n = await sync_kind(kind, full=False)
        logger.info("副本对账完成", extra={"kind": kind, "rows": n})


async def _retry_forever(name: str, func: Callable[[], Awaitable[None]], delay: float = 5.0) -> None:
    while True:
        try:
            await func()
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("%s 失败，稍后重试", name, exc_info=True)
            await asyncio.sleep(delay)


async def run_event_consumer() -> None:
    """运行事件消费者；被取消时先请求优雅停止（避免遗留阻塞读取任务），最多等 3 秒。"""
    consumer = StreamConsumer(STREAM_IAM_EVENTS, GROUP, handle_event)
    inner = asyncio.create_task(consumer.run_forever())
    try:
        await asyncio.shield(inner)
    except asyncio.CancelledError:
        await consumer.stop()
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError, Exception):
            await asyncio.wait_for(inner, timeout=3)
        inner.cancel()
        raise


async def run_reconcile(settings: Settings | None = None) -> None:
    s = settings or get_settings()
    await _retry_forever("副本启动全量同步", initial_sync)
    await run_periodic("open_ref_reconcile", s.REF_RECONCILE_INTERVAL_SECONDS, reconcile)
