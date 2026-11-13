"""鉴权模块的进程内运行时配置：由 create_app 注册 settings，并按需创建访问 iam 的内部客户端。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from platform_common.config import BaseServiceSettings
from platform_common.http_client import InternalClient

if TYPE_CHECKING:
    from platform_common.auth.context import AuthContext

# 上下文加载器：user_id → AuthContext（用户不存在返回 None；依赖不可用抛 BizError(503001)）
ContextLoader = Callable[[int], Awaitable["AuthContext | None"]]

_settings: BaseServiceSettings | None = None
_iam_client: InternalClient | None = None
_context_loader: ContextLoader | None = None


def set_context_loader(loader: ContextLoader | None) -> None:
    """注册缓存未命中时的上下文加载器。

    默认（不注册或传 None）经 HTTP 调 iam 内部接口；iam 自身注册本地 loader，避免回调自己的内部接口。
    """
    global _context_loader
    _context_loader = loader


def get_context_loader() -> ContextLoader | None:
    """已注册的 loader；None 表示使用默认的 HTTP loader。"""
    return _context_loader


def configure(settings: BaseServiceSettings) -> None:
    global _settings
    _settings = settings


def get_settings() -> BaseServiceSettings:
    if _settings is None:
        raise RuntimeError("鉴权未配置，请先调用 create_app 或 auth.runtime.configure(settings)")
    return _settings


def get_iam_client() -> InternalClient:
    global _iam_client
    if _iam_client is None:
        s = get_settings()
        _iam_client = InternalClient(s.IAM_INTERNAL_URL, s.INTERNAL_API_TOKEN, s.INTERNAL_HTTP_TIMEOUT_SECONDS)
    return _iam_client


async def shutdown() -> None:
    global _iam_client
    if _iam_client is not None:
        await _iam_client.aclose()
        _iam_client = None
