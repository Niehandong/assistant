"""统一响应：``{"code": 0, "message": "ok", "data": ...}``。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, PlainSerializer

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def _to_local_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(LOCAL_TZ).isoformat()


# 响应 schema 中使用：输出 ISO 8601 带时区（+08:00）
LocalDatetime = Annotated[datetime, PlainSerializer(_to_local_iso, return_type=str, when_used="json")]


class ApiResponse[T](BaseModel):
    code: int = 0
    message: str = "ok"
    data: T | None = None


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    return {"code": 0, "message": message, "data": data}


def page(items: Sequence[Any], total: int, page: int, page_size: int) -> dict[str, Any]:  # noqa: A002
    return ok({"items": list(items), "total": total, "page": page, "page_size": page_size})
