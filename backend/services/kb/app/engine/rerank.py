"""重排适配：把 ``RerankClient`` 包装成引擎使用的 ``Reranker``，并处理得分归一化。"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable, Sequence

from app.model_clients.rerank import RerankClient

# (查询, 候选文本列表) -> 与候选同序的得分；模型调用失败抛 ModelClientError
Reranker = Callable[[str, list[str]], Awaitable[list[float]]]

RERANK_SKIPPED_REASON = "重排模型不可用，已跳过重排"


def normalize_scores(raw: Sequence[float]) -> list[float]:
    """任一分值不在 [0, 1] 时对全部做 sigmoid，否则原样返回。"""
    if all(0.0 <= v <= 1.0 for v in raw):
        return list(raw)
    return [1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, v)))) for v in raw]


def make_reranker(client: RerankClient) -> Reranker:
    async def _rerank(query: str, texts: list[str]) -> list[float]:
        results = await client.rerank(query, texts, top_n=len(texts))
        by_index = {r.index: r.relevance_score for r in results}
        # 服务端少返回的候选视为最低分
        floor = min(by_index.values()) if by_index else 0.0
        raw = [by_index.get(i, floor) for i in range(len(texts))]
        return normalize_scores(raw)

    return _rerank
