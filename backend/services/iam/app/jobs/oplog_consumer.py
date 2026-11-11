"""操作日志消费者：stream:oplog -> iam.sys_operation_log（消费组 iam-oplog）。"""

from __future__ import annotations

from app.services.log_service import handle_oplog_message
from platform_common.events.consumer import StreamConsumer
from platform_common.events.streams import STREAM_OPLOG

GROUP = "iam-oplog"


def build_consumer() -> StreamConsumer:
    return StreamConsumer(STREAM_OPLOG, GROUP, handle_oplog_message)
