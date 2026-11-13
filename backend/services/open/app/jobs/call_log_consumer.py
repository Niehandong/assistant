"""调用日志消费端（tech-design-m3 3.4）：``stream:open.call_logs`` → ``open.api_call_log``。

* 消费组 ``open-calllog``，每批最多 200 条，一条 ``INSERT ... ON CONFLICT (request_id) DO NOTHING`` 批量入库，
  入库成功后整批 XACK（至少一次投递，request_id 唯一键保证重复投递幂等）。
* 批量入库失败（数据库故障或批内含坏数据）时退回共享库 ``StreamConsumer`` 的逐条路径：按消息重试，
  累计失败达上限进入 ``stream:dead``，不会因为一条坏消息阻塞整个流。
* 多实例安全：同一消费组内每条消息只会被一个实例处理。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import ApiCallLog
from app.schemas.retrieve import QUERY_MAX_LEN, CallLogPayload
from platform_common.db import get_session_factory
from platform_common.events.consumer import StreamConsumer
from platform_common.events.streams import MESSAGE_FIELD, STREAM_OPEN_CALL_LOGS
from platform_common.redis import get_redis

logger = logging.getLogger(__name__)

GROUP = "open-calllog"
BATCH = 200
QUERY_COLUMN_MAX = 2000

Entry = tuple[str, dict[str, str]]


def to_row(payload: dict[str, Any]) -> dict[str, Any]:
    """事件载荷 → ``api_call_log`` 行（校验类型；去掉 NUL，截断超长文本以免入库失败）。"""
    p = CallLogPayload.model_validate(payload)
    row = p.model_dump()
    row["request_id"] = p.request_id[:64]
    for col, size in (("key_name", 50), ("key_prefix", 16), ("dataset_name", 50), ("client_ip", 64)):
        if row[col] is not None:
            row[col] = row[col].replace("\x00", "")[:size]
    if row["query"] is not None:
        row["query"] = row["query"].replace("\x00", "")[: max(QUERY_COLUMN_MAX, QUERY_MAX_LEN)]
    return row


async def insert_rows(rows: list[dict[str, Any]]) -> int:
    """批量插入，返回实际新增行数（重复 request_id 被忽略）。"""
    if not rows:
        return 0
    stmt = pg_insert(ApiCallLog).values(rows).on_conflict_do_nothing(index_elements=["request_id"])
    async with get_session_factory()() as session:
        result = await session.execute(stmt)
        await session.commit()
    return int(getattr(result, "rowcount", 0) or 0)


async def handle_one(envelope: dict[str, Any]) -> None:
    await insert_rows([to_row(envelope["payload"])])


class CallLogConsumer(StreamConsumer):
    def __init__(self, *, batch: int = BATCH, **kwargs: Any) -> None:
        super().__init__(STREAM_OPEN_CALL_LOGS, GROUP, handle_one, batch=batch, **kwargs)

    async def _process(self, entries: list[Entry]) -> None:  # 覆盖：先走批量路径
        rows: list[dict[str, Any]] = []
        good: list[Entry] = []
        fallback: list[Entry] = []
        for entry in entries:
            try:
                envelope = json.loads(entry[1][MESSAGE_FIELD])
                rows.append(to_row(envelope["payload"]))
                good.append(entry)
            except (KeyError, TypeError, ValueError, ValidationError):
                fallback.append(entry)  # 交给基类：JSON 不合法直接进死信，其余按重试规则处理
        if rows:
            try:
                await insert_rows(rows)
                await get_redis().xack(self.stream, self.group, *[mid for mid, _ in good])
            except Exception:
                logger.error("调用日志批量入库失败，退回逐条处理", exc_info=True, extra={"size": len(rows)})
                fallback.extend(good)
        if fallback:
            await super()._process(fallback)


async def run_call_log_consumer() -> None:
    await CallLogConsumer().run_forever()
