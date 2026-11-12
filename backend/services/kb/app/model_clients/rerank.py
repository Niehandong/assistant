"""Rerank 客户端：``POST {base_url}/rerank``，响应含 ``results[].index`` 与 ``results[].relevance_score``。"""

from __future__ import annotations

from dataclasses import dataclass

from app.model_clients.base import BaseModelClient
from app.model_clients.errors import ModelBadResponse


@dataclass(frozen=True)
class RerankResult:
    index: int
    relevance_score: float


class RerankClient(BaseModelClient):
    async def rerank(self, query: str, documents: list[str], top_n: int | None = None) -> list[RerankResult]:
        """返回按服务端顺序的结果（通常为得分降序）；index 指向 ``documents``。"""
        if not documents:
            return []
        payload = {
            "model": self.model_name,
            "query": query,
            "documents": documents,
            "top_n": top_n or len(documents),
            "return_documents": False,
        }
        body = await self._post_json("/rerank", payload)
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            raise ModelBadResponse("响应缺少 results")
        out: list[RerankResult] = []
        for item in results:
            idx = item.get("index") if isinstance(item, dict) else None
            score = item.get("relevance_score") if isinstance(item, dict) else None
            if (
                not isinstance(idx, int)
                or isinstance(idx, bool)
                or not 0 <= idx < len(documents)
                or not isinstance(score, int | float)
                or isinstance(score, bool)
            ):
                raise ModelBadResponse("results 中缺少合法的 index 或 relevance_score")
            out.append(RerankResult(idx, float(score)))
        return out
