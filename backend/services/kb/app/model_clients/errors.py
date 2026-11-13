"""模型服务调用错误分类。上层据此映射 error_code（EMBEDDING_TIMEOUT / EMBEDDING_ERROR 等）或 503301。"""

from __future__ import annotations


class ModelClientError(Exception):
    """模型调用错误基类；``str(exc)`` 为可展示给用户的简述（不含凭据）。"""


class ModelTimeout(ModelClientError):
    """连接/读取超时（已按重试策略重试后仍超时）。"""

    def __init__(self, message: str = "请求超时") -> None:
        super().__init__(message)


class ModelHTTPError(ModelClientError):
    """模型服务返回非 2xx，或网络层连接失败（此时 ``status_code`` 为 None）。"""

    def __init__(self, status_code: int | None, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class ModelBadResponse(ModelClientError):
    """响应格式不符合协议（缺字段、数量不一致等）。"""
