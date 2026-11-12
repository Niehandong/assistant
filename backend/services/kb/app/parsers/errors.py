"""解析/分段阶段的业务异常（可跨进程池序列化）。"""

from __future__ import annotations

from typing import Any

from platform_common.errors import BizError

UNSUPPORTED_TYPE = 400501
FILE_TOO_LARGE = 400502
FILE_EMPTY = 400503
FILE_BROKEN = 400504  # 已加密 / 已损坏 / 解析超时
NO_TEXT = 400505
FULL_DOC_TOO_LONG = 400506
INVALID_RULE = 400001


class ProcessError(Exception):
    """解析与分段错误。``reason`` 为稳定的机器可读标识（ENCRYPTED/CORRUPT/TIMEOUT/NO_TEXT/...）。

    纯函数库内不依赖 FastAPI；由调用方（BE-17/BE-18）通过 :meth:`to_biz_error` 转为 BizError。
    """

    def __init__(self, code: int, message: str, reason: str = "", data: Any = None) -> None:
        super().__init__(code, message, reason, data)
        self.code = code
        self.message = message
        self.reason = reason
        self.data = data

    def __str__(self) -> str:
        return f"{self.reason or self.code}: {self.message}"

    def to_biz_error(self) -> BizError:
        return BizError(self.code, self.message, self.data)


def broken(message: str = "文件已加密或已损坏", reason: str = "CORRUPT") -> ProcessError:
    return ProcessError(FILE_BROKEN, message, reason)
