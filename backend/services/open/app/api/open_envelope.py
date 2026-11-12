"""开放检索的统一错误信封中间件（tech-design-m3 BE-27）。

对 ``/api/v1/open/`` 前缀：

1. 请求进入时确定 ``X-Request-Id``：调用方带了且格式合法（1~64 位字母数字 ``._:-``）则沿用，否则生成；
   写回请求头，使内层 ``RequestContextMiddleware`` 使用同一个值。
2. 路由 ``open_retrieve.retrieve`` 自己生成响应并写日志（``scope.state.open_handled``）。其余任何 4xx/5xx
   响应（输入防护中间件拒绝含 NUL 的请求 400001、404/405、框架/全局处理器兜底的 400001/503001/500000 等）
   由这里补齐 ``data.error_type`` 与 ``data.request_id``（message 沿用原响应，即共享库 ``CommonErrors`` 原文），
   并且对开放检索的 POST 请求补写一条调用日志（此时尚未识别密钥，按"无法识别"采样）。
3. 内层异常逃逸时（理论上不会）渲染 500000 信封，同样补写日志。
"""

from __future__ import annotations

import json
import logging
import re
import uuid

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.v1.open_retrieve import HANDLED_STATE_KEY
from app.core.config import Settings
from app.services.call_log_writer import CallContext, record
from app.services.retrieve_service import error_body, parse_dataset_id
from platform_common.client_ip import get_client_ip
from platform_common.errors import CommonErrors

logger = logging.getLogger(__name__)

OPEN_PREFIX = "/api/v1/open/"
_RETRIEVE_PATH = re.compile(r"^/api/v1/open/datasets/([^/]*)/retrieve/?$")
_RID_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,64}$")


class OpenEnvelopeMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path: str = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith(OPEN_PREFIX):
            await self.app(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        rid, supplied = self._request_id(scope)
        state["open_client_rid"] = supplied
        scope["headers"] = [(k, v) for k, v in scope["headers"] if k.lower() != b"x-request-id"] + [
            (b"x-request-id", rid.encode())
        ]
        ctx = self._new_context(scope, rid, supplied, path)

        started: Message | None = None
        chunks: list[bytes] = []
        mode = {"v": "pending"}  # pending → pass / buffer

        async def finish_buffered() -> None:
            assert started is not None
            raw = b"".join(chunks)
            status = int(started["status"])
            try:
                body = json.loads(raw)
                ok = isinstance(body, dict) and isinstance(body.get("code"), int)
            except ValueError:
                body, ok = None, False
            headers = [(k, v) for k, v in started.get("headers", []) if k.lower() not in (b"content-length",)]
            if ok:
                code = int(body["code"])
                extra = body.get("data") if isinstance(body.get("data"), dict) else None
                new = error_body(code, str(body.get("message", "")), rid, extra)
                raw = json.dumps(new, ensure_ascii=False).encode()
                await self._log(ctx, scope, code)
            elif status >= 400:
                await self._log(
                    ctx, scope, CommonErrors.INTERNAL[0] if status >= 500 else CommonErrors.INVALID_PARAMS[0]
                )
            headers.append((b"content-length", str(len(raw)).encode()))
            await send({**started, "headers": headers})
            await send({"type": "http.response.body", "body": raw})

        async def send_wrapper(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                if message["status"] >= 400 and not state.get(HANDLED_STATE_KEY):
                    mode["v"], started = "buffer", message
                    return
                mode["v"] = "pass"
            elif message["type"] == "http.response.body" and mode["v"] == "buffer":
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    await finish_buffered()
                return
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            if mode["v"] != "pending":
                raise
            logger.error("开放检索请求处理异常", exc_info=True)
            code, message = CommonErrors.INTERNAL
            await self._log(ctx, scope, code)
            raw = json.dumps(error_body(code, message, rid), ensure_ascii=False).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(raw)).encode()),
                        (b"x-request-id", rid.encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": raw})

    @staticmethod
    def _request_id(scope: Scope) -> tuple[str, bool]:
        for k, v in scope.get("headers", []):
            if k.lower() == b"x-request-id":
                value = v.decode("latin-1")
                if _RID_RE.match(value):
                    return value, True
        return uuid.uuid4().hex, False

    def _new_context(self, scope: Scope, rid: str, supplied: bool, path: str) -> CallContext | None:
        m = _RETRIEVE_PATH.match(path)
        if m is None or scope.get("method") != "POST":
            return None
        return CallContext(
            request_id=rid,
            client_ip=get_client_ip(Request(scope), self.settings.TRUSTED_PROXIES),
            client_supplied_id=supplied,
            dataset_id=parse_dataset_id(m.group(1)),
        )

    @staticmethod
    async def _log(ctx: CallContext | None, scope: Scope, code: int) -> None:
        if ctx is not None:
            await record(ctx, code)
