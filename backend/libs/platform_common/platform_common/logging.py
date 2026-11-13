"""结构化（JSON）日志与 request_id 上下文。"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


def get_request_id() -> str | None:
    return _request_id_var.get()


def set_request_id(request_id: str | None) -> None:
    _request_id_var.set(request_id)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "request_id": get_request_id(),
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():  # logger.info(..., extra={...})
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(service: str, level: str = "INFO") -> None:
    """配置根日志为 JSON 输出到 stdout（幂等）。"""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_kbp", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler._kbp = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonFormatter(service))
    root.addHandler(handler)
    root.setLevel(level.upper())
    # uvicorn 自带访问日志由 app_factory 的访问日志中间件取代
    logging.getLogger("uvicorn.access").disabled = True
