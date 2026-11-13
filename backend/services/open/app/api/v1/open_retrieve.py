"""开放检索 API（tech-design-m3 5.4）。**public**：外部系统不登录，凭 API 密钥鉴权（鉴权链见 3.3）。

路由层只收参并调用 ``retrieve_service.handle``；该函数永不抛出，所有错误都转换成带 ``error_type`` / ``request_id``
的统一响应，并写且只写一条调用日志。因此不使用 FastAPI 的前置参数校验（校验排在密钥/限流之后）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.schemas.retrieve import ErrorResponse, RetrieveRequest, RetrieveSuccess
from app.services import retrieve_service
from app.services.retrieve_service import Inbound
from platform_common.client_ip import get_client_ip

router = APIRouter(prefix="/open", tags=["open-retrieve"])

HANDLED_STATE_KEY = "open_handled"  # 已由本路由生成响应并写过日志；外层中间件据此不再重复处理

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "400001 INVALID_PARAMS 参数不合法（data.errors 指出字段）"},
    401: {"model": ErrorResponse, "description": "401601 KEY_INVALID 密钥缺失或无效"},
    403: {
        "model": ErrorResponse,
        "description": (
            "403601 KEY_DISABLED 密钥已停用 / 403602 KEY_EXPIRED 密钥已过期 / 403603 IP_NOT_ALLOWED IP 不在白名单"
        ),
    },
    404: {"model": ErrorResponse, "description": "404601 DATASET_NOT_FOUND 知识库不存在或未授权"},
    429: {
        "model": ErrorResponse,
        "description": "429601 RATE_LIMITED 调用超限，请下一分钟再试；响应头 Retry-After 为距下一分钟的秒数",
    },
    500: {"model": ErrorResponse, "description": "500000 INTERNAL_ERROR 系统繁忙，请稍后重试"},
    503: {
        "model": ErrorResponse,
        "description": (
            "503601 MODEL_UNAVAILABLE 模型服务不可用 / 503001 SERVICE_UNAVAILABLE 依赖服务暂不可用，请稍后重试"
        ),
    },
}


@router.post(
    "/datasets/{dataset_id}/retrieve",
    summary="开放检索（public，凭 API 密钥 Authorization: Bearer 鉴权）",
    response_model=RetrieveSuccess,
    responses=_ERROR_RESPONSES,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": RetrieveRequest.model_json_schema()}},
        }
    },
)
async def retrieve(
    request: Request,
    dataset_id: Annotated[str, Path(description="知识库 ID（正整数）", json_schema_extra={"type": "integer"})],
) -> JSONResponse:
    async def read_body() -> bytes:
        return await _read_capped(request)

    supplied = request.headers.get("x-request-id")
    rid = getattr(request.state, "request_id", None) or supplied or "-"
    outcome = await retrieve_service.handle(
        Inbound(
            request_id=rid,
            client_ip=get_client_ip(request, get_settings().TRUSTED_PROXIES),
            authorization=request.headers.get("authorization"),
            dataset_id_raw=dataset_id,
            read_body=read_body,
            client_supplied_id=bool(getattr(request.state, "open_client_rid", False)),
        )
    )
    request.state.open_handled = True  # handle 正常返回才算已处理；异常逃逸交给外层中间件补信封与日志
    return JSONResponse(outcome.body, status_code=outcome.status, headers={**outcome.headers, "X-Request-Id": rid})


async def _read_capped(request: Request) -> bytes:
    """最多读 MAX_BODY_BYTES + 1 字节：超出即停止读取（防止超大请求体占内存），由校验阶段报 400001。"""
    limit = retrieve_service.MAX_BODY_BYTES + 1
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        chunks.append(chunk)
        size += len(chunk)
        if size >= limit:
            break
    return b"".join(chunks)
