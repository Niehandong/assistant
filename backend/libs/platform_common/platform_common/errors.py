"""统一业务异常与通用错误码（总体方案 4.2）。"""

from __future__ import annotations

from typing import Any


class BizError(Exception):
    """业务异常。``code = HTTP 状态码 × 1000 + 序号``，由全局处理器转换为统一响应。"""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    @property
    def http_status(self) -> int:
        return self.code // 1000

    def __repr__(self) -> str:
        return f"BizError(code={self.code}, message={self.message!r})"


class CommonErrors:
    """通用错误码常量，形如 ``(code, message)``，用法：``raise BizError(*CommonErrors.FORBIDDEN)``。"""

    INVALID_PARAMS = (400001, "参数不合法")
    UNAUTHENTICATED = (401001, "未登录或登录已过期")
    SESSION_INVALID = (401002, "会话已失效，请重新登录")
    FORBIDDEN = (403001, "无权限执行该操作")
    MUST_CHANGE_PASSWORD = (403002, "请先修改密码")
    NOT_FOUND = (404000, "无权限或数据不存在")
    VERSION_CONFLICT = (409001, "数据已被他人修改，请刷新后重试")
    TOO_MANY_REQUESTS = (429001, "请求过于频繁")
    INTERNAL = (500000, "系统繁忙，请稍后重试")
    DEPENDENCY_UNAVAILABLE = (503001, "依赖服务暂不可用，请稍后重试")
    INTERNAL_TOKEN_INVALID = (401901, "内部调用凭据无效")


# HTTPException 状态码 → 通用错误码
_HTTP_STATUS_TO_ERROR: dict[int, tuple[int, str]] = {
    400: CommonErrors.INVALID_PARAMS,
    401: CommonErrors.UNAUTHENTICATED,
    403: CommonErrors.FORBIDDEN,
    404: CommonErrors.NOT_FOUND,
    409: CommonErrors.VERSION_CONFLICT,
    429: CommonErrors.TOO_MANY_REQUESTS,
    503: CommonErrors.DEPENDENCY_UNAVAILABLE,
}


def error_from_http_status(status: int) -> tuple[int, str]:
    """把任意 HTTP 状态码映射成 (code, message)；未知 4xx 为 ``status*1000``，5xx 统一 500000。"""
    if status in _HTTP_STATUS_TO_ERROR:
        return _HTTP_STATUS_TO_ERROR[status]
    if status >= 500:
        return CommonErrors.INTERNAL
    return status * 1000, "请求不合法"
