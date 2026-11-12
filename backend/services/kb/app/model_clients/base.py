"""Embedding / Rerank 共用的 HTTP 调用：超时、重试（仅超时与 5xx，共 2 次）、错误分类。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.model_clients.errors import ModelBadResponse, ModelHTTPError, ModelTimeout

logger = logging.getLogger(__name__)

MAX_RETRIES = 2  # 首次调用之外最多再重试 2 次


def _brief(resp: httpx.Response) -> str:
    """错误响应的简述：优先取 JSON 中的 error.message / message，截断到 120 字符；不回显请求内容。"""
    text = ""
    try:
        body = resp.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                text = str(err.get("message") or "")
            elif err:
                text = str(err)
            else:
                text = str(body.get("message") or "")
    except ValueError:
        text = resp.text
    text = " ".join(text.split())[:120]
    return f"HTTP {resp.status_code}" + (f"：{text}" if text else "")


class BaseModelClient:
    def __init__(
        self,
        base_url: str,
        model_name: str,
        api_key: str | None = None,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_backoff: float = 0.5,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport
        self._retry_backoff = retry_backoff
        self._max_retries = max_retries

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def _post_json(self, path: str, payload: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        last: Exception | None = None
        for attempt in range(self._max_retries + 1):
            if attempt:
                await asyncio.sleep(self._retry_backoff * attempt)
            try:
                async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                    resp = await client.post(url, json=payload, headers=self._headers())
            except httpx.TimeoutException as exc:
                last = ModelTimeout()
                logger.warning("模型调用超时", extra={"url": url, "attempt": attempt + 1, "err": type(exc).__name__})
                continue
            except httpx.HTTPError as exc:
                # 连接失败等网络错误：不重试，直接上报
                raise ModelHTTPError(None, "无法连接模型服务，请检查服务地址与网络") from exc
            if resp.status_code >= 500:
                last = ModelHTTPError(resp.status_code, _brief(resp))
                logger.warning("模型服务 5xx", extra={"url": url, "attempt": attempt + 1, "status": resp.status_code})
                continue
            if resp.status_code >= 400:
                raise ModelHTTPError(resp.status_code, _brief(resp))
            try:
                return resp.json()
            except ValueError as exc:
                raise ModelBadResponse("响应不是合法的 JSON") from exc
        assert last is not None
        raise last
