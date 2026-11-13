"""Embedding 客户端：``POST {base_url}/embeddings``，body ``{"model", "input": [...]}``。"""

from __future__ import annotations

from typing import Any

from app.model_clients.base import BaseModelClient
from app.model_clients.errors import ModelBadResponse


class EmbeddingClient(BaseModelClient):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """返回与 ``texts`` 等长、同序的向量列表。"""
        if not texts:
            return []
        body = await self._post_json("/embeddings", {"model": self.model_name, "input": texts})
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list) or len(data) != len(texts):
            raise ModelBadResponse("响应 data 数量与输入不一致")
        items: list[tuple[int, list[float]]] = []
        for pos, item in enumerate(data):
            vector = _extract_vector(item)
            index = item.get("index", pos) if isinstance(item, dict) else pos
            items.append((int(index) if isinstance(index, int) else pos, vector))
        items.sort(key=lambda x: x[0])
        return [vec for _, vec in items]


def _extract_vector(item: Any) -> list[float]:
    vector = item.get("embedding") if isinstance(item, dict) else None
    if not isinstance(vector, list) or not vector or not all(isinstance(v, int | float) for v in vector):
        raise ModelBadResponse("响应缺少合法的 embedding 字段")
    return [float(v) for v in vector]
