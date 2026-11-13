"""请求输入防护（纯 ASGI 中间件）：统一拒绝含 NUL 字符（``\\x00``）的路径、查询串与 JSON 请求体。

PostgreSQL 的 text/jsonb 不接受 NUL，放行会在入库时变成 500；在入口统一返回 400001，各接口无需逐个校验。
整数越界（超出 BIGINT）由 ``app_factory`` 的 ``DataError`` 处理器兜底转换为 400001。
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote_to_bytes

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from platform_common.errors import CommonErrors

MAX_INSPECT_BODY = 2 * 1024 * 1024  # 超过则不解析（交由框架与各接口自身的长度限制处理）
_NUL_ESCAPE = b"\\u0000"


def _has_nul(value: Any) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_has_nul(k) or _has_nul(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_has_nul(v) for v in value)
    return False


def _raw_has_nul(raw: bytes) -> bool:
    return b"\x00" in unquote_to_bytes(raw)


def _is_json(scope: Scope) -> bool:
    for k, v in scope.get("headers", []):
        if k == b"content-type":
            return b"json" in v.lower()
    return False


class InputGuardMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if _raw_has_nul(scope.get("raw_path") or b"") or _raw_has_nul(scope.get("query_string", b"")):
            await self._reject(scope, receive, send)
            return
        if scope["method"] in ("POST", "PUT", "PATCH") and _is_json(scope):
            body, replay = await self._buffer(receive)
            if body is not None and _NUL_ESCAPE in body and self._json_has_nul(body):
                await self._reject(scope, receive, send)
                return
            receive = replay
        await self.app(scope, receive, send)

    @staticmethod
    def _json_has_nul(body: bytes) -> bool:
        try:
            return _has_nul(json.loads(body))
        except ValueError:
            return False  # 非法 JSON 由框架返回 400001

    @staticmethod
    async def _buffer(receive: Receive) -> tuple[bytes | None, Receive]:
        """读完整个请求体后提供可重放的 receive；过大的请求体不检查（原样回放）。"""
        messages: list[Message] = []
        size = 0
        while True:
            msg = await receive()
            messages.append(msg)
            if msg["type"] != "http.request":
                break
            size += len(msg.get("body", b""))
            if not msg.get("more_body", False):
                break
        it = iter(messages)

        async def replay() -> Message:
            try:
                return next(it)
            except StopIteration:
                return await receive()

        if size > MAX_INSPECT_BODY or any(m["type"] != "http.request" for m in messages):
            return None, replay
        return b"".join(m.get("body", b"") for m in messages), replay

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        code, message = CommonErrors.INVALID_PARAMS
        resp = JSONResponse(
            status_code=400,
            content={
                "code": code,
                "message": message,
                "data": {"errors": [{"field": "", "message": "参数包含非法字符"}]},
            },
        )
        await resp(scope, receive, send)
