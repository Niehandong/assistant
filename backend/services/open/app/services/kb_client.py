"""kb 内部接口客户端（tech-design-m2 5.9）。

* ``accessible-datasets`` / ``brief`` 走 ``KB_INTERNAL_URL``（kb 主实例）。
* ``retrieve`` 走 ``KB_RETRIEVAL_URL``（可指向 kb 的"检索组"实例），超时 ``OPEN_RETRIEVE_TIMEOUT_SECONDS``。
* 失败语义由共享库 ``InternalClient`` 决定：连接错误/超时/5xx → ``BizError(503001)``；4xx 透传 kb 的错误码。
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings, get_settings
from platform_common.http_client import InternalClient

# 检索转发是 open 的热路径：共享库默认连接池只保留 20 条长连接，并发 50 时会不断建连/断连。
_POOL_LIMITS = httpx.Limits(max_connections=200, max_keepalive_connections=100, keepalive_expiry=30.0)


class _PooledInternalClient(InternalClient):
    """只调整 httpx 连接池上限（其余行为、错误映射与共享库 ``InternalClient`` 完全一致）。"""

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout, limits=_POOL_LIMITS)
        return self._client


class KbClient:
    def __init__(self, settings: Settings | None = None) -> None:
        s = settings or get_settings()
        self._internal = InternalClient(s.KB_INTERNAL_URL, s.INTERNAL_API_TOKEN, s.INTERNAL_HTTP_TIMEOUT_SECONDS)
        self._retrieval = _PooledInternalClient(
            s.KB_RETRIEVAL_URL, s.INTERNAL_API_TOKEN, s.OPEN_RETRIEVE_TIMEOUT_SECONDS
        )

    async def aclose(self) -> None:
        await self._internal.aclose()
        await self._retrieval.aclose()

    async def accessible_datasets(
        self, user_ids: list[int], dataset_ids: list[int] | None = None
    ) -> dict[int, list[int]]:
        """用户**当前**可访问（所有者 + 被分配）的知识库 ID；用户不可用 → 空列表。user_ids ≤ 100。"""
        body: dict[str, Any] = {"user_ids": user_ids}
        if dataset_ids is not None:
            body["dataset_ids"] = dataset_ids
        data = await self._internal.post("/internal/v1/access/accessible-datasets", json=body)
        items: dict[str, list[int]] = (data or {}).get("items", {})
        return {int(uid): [int(i) for i in ids] for uid, ids in items.items()}

    async def datasets_brief(self, ids: list[int]) -> list[dict[str, Any]]:
        """``[{"id", "name", "is_deleted"}]``（含已删除；ids ≤ 500）。"""
        if not ids:
            return []
        data = await self._internal.post("/internal/v1/datasets/brief", json={"ids": ids})
        return list(data or [])

    async def retrieve(
        self, dataset_id: int, user_id: int, query: str, overrides: dict[str, Any] | None, source: str = "open_api"
    ) -> dict[str, Any]:
        """以 user_id 身份检索（kb 实时判定 ACL）；kb 404000/409303/503301/400001 以 BizError 抛出。"""
        body: dict[str, Any] = {"user_id": user_id, "query": query, "source": source}
        if overrides:
            body["overrides"] = overrides
        data = await self._retrieval.post(f"/internal/v1/datasets/{dataset_id}/retrieve", json=body)
        return dict(data or {})


_client: KbClient | None = None


def get_kb_client() -> KbClient:
    global _client
    if _client is None:
        _client = KbClient()
    return _client


def set_kb_client(client: KbClient | None) -> None:
    """测试注入 / 重置。"""
    global _client
    _client = client


async def close_kb_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
