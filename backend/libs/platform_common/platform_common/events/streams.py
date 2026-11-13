"""Redis Stream 名称与通用常量。"""

from __future__ import annotations

STREAM_IAM_EVENTS = "stream:iam.events"
STREAM_OPLOG = "stream:oplog"
STREAM_KB_TASKS = "stream:kb.tasks"
STREAM_OPEN_CALL_LOGS = "stream:open.call_logs"
STREAM_DEAD = "stream:dead"

STREAM_MAXLEN = 100_000  # XADD MAXLEN ~ 近似裁剪
MESSAGE_FIELD = "data"  # 每条消息只有一个字段：JSON 信封
