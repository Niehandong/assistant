"""操作日志：事件模型、emit（永不抛异常）、oplog_scope、脱敏。"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import Request
from pydantic import BaseModel

from platform_common.auth import runtime
from platform_common.auth.context import AuthContext
from platform_common.client_ip import get_client_ip
from platform_common.errors import BizError, CommonErrors
from platform_common.events.streams import MESSAGE_FIELD, STREAM_MAXLEN, STREAM_OPLOG
from platform_common.logging import get_request_id
from platform_common.redis import get_redis

logger = logging.getLogger(__name__)

MASK = "******"
# 命中即脱敏：password/passwd/secret/api_key/apikey/credential/private_key；以 token 结尾（排除 max_tokens 等复数）
_SENSITIVE = re.compile(r"(password|passwd|secret|api_?key|credential|private_?key|(^|_)token$)", re.IGNORECASE)


class OpLogEvent(BaseModel):
    event_id: str
    service: str
    occurred_at: datetime
    operator_id: int
    operator_username: str
    operator_name: str
    company_id: int | None
    dept_id: int | None
    module: str
    action: str
    target_type: str
    target_id: str | None
    target_name: str | None
    summary: dict[str, Any] = {}  # {"before": {...}, "after": {...}} 或自定义，已脱敏
    result: Literal["success", "failure"]
    error_message: str | None = None
    ip: str | None
    user_agent: str | None
    request_id: str | None


def mask_sensitive(data: dict[str, Any]) -> dict[str, Any]:
    """递归脱敏：敏感键的值替换为 ``"******"``；返回新对象，不修改入参。"""

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: (MASK if isinstance(k, str) and _SENSITIVE.search(k) else walk(v)) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [walk(v) for v in value]
        return value

    result: dict[str, Any] = walk(data)
    return result


async def emit_oplog(event: OpLogEvent) -> None:
    """写入 stream:oplog；任何异常只记运行日志，不抛出。写入前再次脱敏 summary。"""
    try:
        event = event.model_copy(update={"summary": mask_sensitive(event.summary)})
        await get_redis().xadd(
            STREAM_OPLOG,
            {MESSAGE_FIELD: event.model_dump_json()},
            maxlen=STREAM_MAXLEN,
            approximate=True,
        )
    except Exception:
        logger.error(
            "操作日志写入失败",
            exc_info=True,
            extra={"op_module": event.module, "op_action": event.action, "op_target_id": event.target_id},
        )


class OpLogHandle:
    """scope 内可修改：summary、target_id、target_name；``suppress=True`` 时成功结束不记日志（no-op 操作）。"""

    def __init__(self, target_id: Any, target_name: str | None) -> None:
        self.suppress = False
        self.summary: dict[str, Any] = {}
        self.target_id: str | None = None if target_id is None else str(target_id)
        self.target_name = target_name

    def set_target(self, target_id: Any, target_name: str | None = None) -> None:
        self.target_id = None if target_id is None else str(target_id)
        if target_name is not None:
            self.target_name = target_name


def oplog_scope(
    request: Request,
    ctx: AuthContext,
    *,
    module: str,
    action: str,
    target_type: str,
    target_id: Any = None,
    target_name: str | None = None,
) -> AbstractAsyncContextManager[OpLogHandle]:
    """正常结束记 success；抛 BizError 记 failure（含 message）后继续抛出；其他异常记 failure(系统繁忙) 后抛出。"""

    @asynccontextmanager
    async def _scope() -> AsyncIterator[OpLogHandle]:
        handle = OpLogHandle(target_id, target_name)
        result: Literal["success", "failure"] = "success"
        error: str | None = None
        try:
            yield handle
        except BizError as exc:
            result, error = "failure", exc.message
            raise
        except Exception:
            result, error = "failure", CommonErrors.INTERNAL[1]
            raise
        finally:
            if result == "failure" or not handle.suppress:
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
                        module=module,
                        action=action,
                        target_type=target_type,
                        target_id=handle.target_id,
                        target_name=handle.target_name,
                        summary=handle.summary,
                        result=result,
                        error_message=error,
                        ip=get_client_ip(request, settings.TRUSTED_PROXIES),
                        user_agent=request.headers.get("user-agent"),
                        request_id=get_request_id(),
                    )
                )

    return _scope()
