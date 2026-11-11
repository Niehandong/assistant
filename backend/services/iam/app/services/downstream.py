"""下游服务（kb / open）统计调用，供删除组织、用户影响提示使用。

* 开关 ``KB_STATS_ENABLED`` / ``OPEN_STATS_ENABLED`` 默认 false（M1 下游尚未部署）：关闭时直接返回 ``None``，
  表示"未统计"，调用方按各自规则降级（删除组织跳过检查；影响提示置 null 且 degraded=true）。
* 开关开启后调用失败：抛 ``BizError(503001)``（由 ``InternalClient`` 统一映射）；需要降级的调用方（影响提示）
  使用 ``*_safe`` 版本，失败时同样返回 ``None``。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app.core.config import Settings, get_settings
from platform_common.errors import BizError
from platform_common.http_client import InternalClient

logger = logging.getLogger(__name__)

_clients: dict[str, InternalClient] = {}


def _client(name: str, base_url: str, settings: Settings) -> InternalClient:
    key = f"{name}|{base_url}"
    client = _clients.get(key)
    if client is None:
        client = InternalClient(base_url, settings.INTERNAL_API_TOKEN, settings.INTERNAL_HTTP_TIMEOUT_SECONDS)
        _clients[key] = client
    return client


async def close_clients() -> None:
    for c in list(_clients.values()):
        await c.aclose()
    _clients.clear()


@asynccontextmanager
async def lifespan_hook(_app: FastAPI) -> AsyncIterator[None]:
    """create_app 的 lifespan 钩子：退出时关闭下游 HTTP 客户端。"""
    try:
        yield
    finally:
        await close_clients()


def _count(data: Any) -> int:
    return int(data["count"])


async def kb_dataset_count_by_dept(dept_id: int) -> int | None:
    """某部门/公司节点下未删除知识库数；开关关闭返回 None；失败抛 503001。"""
    s = get_settings()
    if not s.KB_STATS_ENABLED:
        return None
    data = await _client("kb", s.KB_INTERNAL_URL, s).get("/internal/v1/stats/datasets", params={"dept_id": dept_id})
    return _count(data)


async def kb_dataset_count_by_owner(owner_id: int) -> int | None:
    """某用户拥有的未删除知识库数；开关关闭返回 None；失败抛 503001。"""
    s = get_settings()
    if not s.KB_STATS_ENABLED:
        return None
    data = await _client("kb", s.KB_INTERNAL_URL, s).get("/internal/v1/stats/datasets", params={"owner_id": owner_id})
    return _count(data)


async def open_api_key_count_by_user(user_id: int) -> int | None:
    """某用户未删除的 API 密钥数；开关关闭返回 None；失败抛 503001。"""
    s = get_settings()
    if not s.OPEN_STATS_ENABLED:
        return None
    data = await _client("open", s.OPEN_INTERNAL_URL, s).get("/internal/v1/stats/api-keys", params={"user_id": user_id})
    return _count(data)


async def kb_dataset_count_by_owner_safe(owner_id: int) -> int | None:
    try:
        return await kb_dataset_count_by_owner(owner_id)
    except (BizError, KeyError, TypeError, ValueError):
        logger.warning("kb 统计调用失败，降级为 null owner_id=%s", owner_id, exc_info=True)
        return None


async def open_api_key_count_by_user_safe(user_id: int) -> int | None:
    try:
        return await open_api_key_count_by_user(user_id)
    except (BizError, KeyError, TypeError, ValueError):
        logger.warning("open 统计调用失败，降级为 null user_id=%s", user_id, exc_info=True)
        return None
