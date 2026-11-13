"""kb 操作日志的直接写入辅助（管理视图审计、批量转移的逐条日志）。``emit_oplog`` 永不抛异常。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request

from platform_common.auth import runtime
from platform_common.auth.context import AuthContext
from platform_common.client_ip import get_client_ip
from platform_common.logging import get_request_id
from platform_common.oplog import OpLogEvent, emit_oplog


async def log_dataset_event(
    request: Request, ctx: AuthContext, action: str, dataset_id: int, dataset_name: str, summary: dict[str, Any]
) -> None:
    settings = runtime.get_settings()
    await emit_oplog(
        OpLogEvent(
            event_id=str(uuid.uuid4()),
            service=settings.SERVICE_NAME,
            occurred_at=datetime.now(UTC),
            operator_id=ctx.user_id,
            operator_username=ctx.username,
            operator_name=ctx.name,
            company_id=ctx.company_id,
            dept_id=ctx.org_id,
            module="dataset",
            action=action,
            target_type="dataset",
            target_id=str(dataset_id),
            target_name=dataset_name,
            summary=summary,
            result="success",
            ip=get_client_ip(request, settings.TRUSTED_PROXIES),
            user_agent=request.headers.get("user-agent"),
            request_id=get_request_id(),
        )
    )
