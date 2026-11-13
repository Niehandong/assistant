"""开放检索 API 的请求/响应模型（tech-design-m3 5.4）与调用日志事件载荷（3.4）。

请求体**不**由 FastAPI 前置校验：鉴权链（3.3）规定参数校验（400001）排在密钥/IP/限流之后，
因此由 ``retrieve_service`` 在鉴权通过后手动用 ``RetrieveRequest`` 校验，并把失败转成 ``data.errors``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError, field_validator

QUERY_MAX_LEN = 1000
TOP_K_MIN, TOP_K_MAX = 1, 20

SearchMethod = Literal["vector", "full_text", "hybrid"]
CallResultName = Literal[
    "success",
    "key_invalid",
    "key_disabled",
    "key_expired",
    "ip_not_allowed",
    "dataset_not_found",
    "invalid_params",
    "rate_limited",
    "model_unavailable",
    "service_unavailable",
    "internal_error",
]


class RetrieveRequest(BaseModel):
    """请求体（未知字段忽略；可选项显式传 null 视为未传）。"""

    model_config = ConfigDict(extra="ignore")

    query: StrictStr
    search_method: SearchMethod | None = None
    top_k: Annotated[StrictInt, Field(ge=TOP_K_MIN, le=TOP_K_MAX)] | None = None
    score_threshold: Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)] | None = None
    reranking_enable: StrictBool | None = None

    @field_validator("query")
    @classmethod
    def _query_rule(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > QUERY_MAX_LEN:
            raise ValueError(f"长度 1~{QUERY_MAX_LEN} 个字符，且不能全为空白")
        return v

    def overrides(self) -> dict[str, Any]:
        """传给 kb 内部检索的 overrides（只含调用方显式传入的项）。"""
        out: dict[str, Any] = {}
        for name in ("search_method", "top_k", "score_threshold", "reranking_enable"):
            value = getattr(self, name)
            if value is not None:
                out[name] = value
        return out


_TYPE_MESSAGES: dict[str, str] = {
    "missing": "必填",
    "string_type": "必须为字符串",
    "int_type": "必须为整数",
    "int_parsing": "必须为整数",
    "float_type": "必须为数字",
    "float_parsing": "必须为数字",
    "bool_type": "必须为布尔值",
    "literal_error": "可选值：vector、full_text、hybrid",
    "finite_number": "必须为有限数字",
}
_RANGE_MESSAGES: dict[str, str] = {
    "top_k": f"取值范围 {TOP_K_MIN}~{TOP_K_MAX}",
    "score_threshold": "取值范围 0~1",
}
_RANGE_TYPES = {"greater_than_equal", "less_than_equal", "greater_than", "less_than"}


def validation_errors(exc: ValidationError) -> list[dict[str, str]]:
    """把 pydantic 错误转成 ``[{"field", "message"}]``（中文说明，不回显用户输入值）。"""
    out: list[dict[str, str]] = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err.get("loc", ()))
        etype = err.get("type", "")
        if etype == "value_error":
            message = str(err.get("msg", "")).removeprefix("Value error, ")
        elif etype in _RANGE_TYPES and field in _RANGE_MESSAGES:
            message = _RANGE_MESSAGES[field]
        else:
            message = _TYPE_MESSAGES.get(etype, "取值不合法")
        out.append({"field": field, "message": message})
    return out


# --------------------------------------------------------------------------- 响应


class NamedRef(BaseModel):
    id: int
    name: str


class RetrievalConfigOut(BaseModel):
    """本次实际使用的检索参数（不含内部的 reranking_model_id）。"""

    search_method: SearchMethod
    top_k: int
    score_threshold_enabled: bool
    score_threshold: float
    reranking_enable: bool
    reranking_model_name: str | None = None
    hybrid_mode: Literal["weighted", "rerank"]
    vector_weight: float


class ChildChunkOut(BaseModel):
    id: int
    position: int
    content: str
    score: float


class RecordOut(BaseModel):
    segment_id: int
    position: int
    segment_type: Literal["general", "parent"]
    content: str
    score: float
    keywords: list[str]
    document: NamedRef
    dataset: NamedRef
    child_chunks: list[ChildChunkOut]


class RetrieveData(BaseModel):
    request_id: str
    dataset: NamedRef
    query: str
    retrieval_config: RetrievalConfigOut
    rerank_skipped: bool
    rerank_skipped_reason: str | None
    records: list[RecordOut]


class RetrieveSuccess(BaseModel):
    code: int = 0
    message: str = "ok"
    data: RetrieveData


class ErrorData(BaseModel):
    error_type: str
    request_id: str
    errors: list[dict[str, str]] | None = Field(default=None, description="仅 400001：出错字段与说明")


class ErrorResponse(BaseModel):
    code: int
    message: str
    data: ErrorData


# --------------------------------------------------------------------------- 调用日志事件载荷


class CallLogPayload(BaseModel):
    """``stream:open.call_logs`` 事件载荷（envelope.payload），字段同 ``open.api_call_log``。"""

    request_id: str
    api_key_id: int | None = None
    key_name: str | None = None
    key_prefix: str | None = None
    company_id: int | None = None
    dept_id: int | None = None
    dataset_id: int | None = None
    dataset_name: str | None = None
    query: str | None = None
    result_count: int = 0
    latency_ms: int
    result: CallResultName
    error_code: int | None = None
    client_ip: str | None = None
    called_at: datetime
    created_by: int = 0  # 密钥创建人；无法识别密钥为 0
