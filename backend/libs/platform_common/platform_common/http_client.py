"""服务间内部调用客户端。"""

from __future__ import annotations

from typing import Any

import httpx

from platform_common.errors import BizError, CommonErrors, error_from_http_status
from platform_common.logging import get_request_id


class InternalClient:
    """带 ``X-Internal-Token`` / ``X-Request-Id``、超时与错误映射的 httpx 封装。

    成功时返回统一响应中的 ``data``；连接错误/超时/5xx → ``BizError(503001)``；4xx 透传为对应 BizError。
    """

    def __init__(self, base_url: str, token: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict[str, str]:
        headers = {"X-Internal-Token": self._token}
        if (rid := get_request_id()) is not None:
            headers["X-Request-Id"] = rid
        return headers

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, *, json: Any = None, params: dict[str, Any] | None = None) -> Any:
        return await self._request("POST", path, json=json, params=params)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = await self._get_client().request(method, path, headers=self._headers(), **kwargs)
        except httpx.HTTPError as exc:  # 连接错误、超时、协议错误
            raise BizError(*CommonErrors.DEPENDENCY_UNAVAILABLE) from exc
        if resp.status_code >= 500:
            raise BizError(*CommonErrors.DEPENDENCY_UNAVAILABLE)
        body = self._parse_body(resp)
        if resp.status_code >= 400:
            if body is not None:
                raise BizError(int(body["code"]), str(body.get("message", "")), body.get("data"))
            code, message = error_from_http_status(resp.status_code)
            raise BizError(code, message)
        if body is None:
            raise BizError(*CommonErrors.DEPENDENCY_UNAVAILABLE)
        if body["code"] != 0:
            raise BizError(int(body["code"]), str(body.get("message", "")), body.get("data"))
        return body.get("data")

    @staticmethod
    def _parse_body(resp: httpx.Response) -> dict[str, Any] | None:
        try:
            body = resp.json()
        except ValueError:
            return None
        if isinstance(body, dict) and isinstance(body.get("code"), int):
            return body
        return None
