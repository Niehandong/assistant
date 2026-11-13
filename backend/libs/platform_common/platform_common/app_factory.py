"""应用工厂：统一中间件、异常处理、健康检查与生命周期。"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from platform_common.auth import runtime as auth_runtime
from platform_common.client_ip import get_client_ip
from platform_common.config import BaseServiceSettings
from platform_common.db import dispose_db, get_engine, init_db
from platform_common.errors import BizError, CommonErrors, error_from_http_status
from platform_common.input_guard import InputGuardMiddleware
from platform_common.logging import set_request_id, setup_logging
from platform_common.redis import close_redis, get_redis, init_redis

logger = logging.getLogger("platform_common.access")

REQUEST_ID_HEADER = "X-Request-Id"
LifespanHook = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def _json(status: int, code: int, message: str, data: Any = None, request_id: str | None = None) -> JSONResponse:
    headers = {REQUEST_ID_HEADER: request_id} if request_id else None
    return JSONResponse(status_code=status, content={"code": code, "message": message, "data": data}, headers=headers)


def _request_id_of(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    return rid if isinstance(rid, str) else None


class RequestContextMiddleware:
    """纯 ASGI 中间件：生成/透传 X-Request-Id、写响应头、输出访问日志。"""

    def __init__(self, app: ASGIApp, trusted_proxies: Sequence[str]) -> None:
        self.app = app
        self.trusted_proxies = list(trusted_proxies)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        set_request_id(request_id)
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if scope["path"] not in ("/healthz", "/readyz"):
                logger.info(
                    "access",
                    extra={
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status_holder["status"],
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                        "ip": get_client_ip(request, self.trusted_proxies),
                    },
                )


def _validation_errors(exc: RequestValidationError) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path", "header", "cookie")]
        errors.append({"field": ".".join(loc), "message": str(err.get("msg", ""))})
    return errors


def _is_data_error(exc: DBAPIError) -> bool:
    """SQLSTATE 22xxx（data exception）：BIGINT 溢出、非法编码/NUL 字符、非法文本表示等。

    asyncpg 在客户端编码参数失败时抛 ``asyncpg.exceptions.DataError``，SQLAlchemy 将其包成通用 DBAPIError，
    因此同时检查包装后的 ``pgcode`` 与原始异常的 ``sqlstate``。
    """
    orig = exc.orig
    cause = getattr(orig, "__cause__", None)
    for candidate in (getattr(orig, "pgcode", None), getattr(cause, "sqlstate", None)):
        if isinstance(candidate, str) and candidate.startswith("22"):
            return True
    return type(cause).__name__.endswith("DataError") or type(orig).__name__ == "DataError"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BizError)
    async def _biz(request: Request, exc: BizError) -> JSONResponse:
        return _json(exc.http_status, exc.code, exc.message, exc.data, _request_id_of(request))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        code, message = CommonErrors.INVALID_PARAMS
        return _json(400, code, message, {"errors": _validation_errors(exc)}, _request_id_of(request))

    @app.exception_handler(DBAPIError)
    async def _db_error(request: Request, exc: DBAPIError) -> JSONResponse:
        rid = _request_id_of(request)
        extra = {"method": request.method, "path": request.url.path}
        if _is_data_error(exc):
            # 参数值超出数据库类型范围（如超大整数）、非法字符等：属于调用方输入问题，不是服务端故障
            logger.warning("数据库拒绝参数值", extra=extra)
            code, message = CommonErrors.INVALID_PARAMS
            return _json(400, code, message, {"errors": [{"field": "", "message": "参数值超出允许范围"}]}, rid)
        if isinstance(exc, OperationalError | InterfaceError):
            logger.error("数据库不可用", exc_info=exc, extra=extra)
            code, message = CommonErrors.DEPENDENCY_UNAVAILABLE
            return _json(503, code, message, None, rid)
        logger.error("数据库异常", exc_info=exc, extra=extra)
        code, message = CommonErrors.INTERNAL
        return _json(500, code, message, None, rid)

    @app.exception_handler(PoolTimeoutError)
    @app.exception_handler(RedisError)
    async def _dependency(request: Request, exc: Exception) -> JSONResponse:
        # 连接池耗尽、数据库/Redis 不可用：明确报 503001（可重试），不暴露细节
        logger.error("依赖不可用", exc_info=exc, extra={"method": request.method, "path": request.url.path})
        code, message = CommonErrors.DEPENDENCY_UNAVAILABLE
        return _json(503, code, message, None, _request_id_of(request))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = error_from_http_status(exc.status_code)
        return _json(code // 1000, code, message, None, _request_id_of(request))

    @app.exception_handler(Exception)
    async def _unknown(request: Request, exc: Exception) -> JSONResponse:
        logger.error("未处理异常", exc_info=exc, extra={"method": request.method, "path": request.url.path})
        code, message = CommonErrors.INTERNAL
        return _json(500, code, message, None, _request_id_of(request))


def _register_health(app: FastAPI) -> None:
    @app.get("/healthz", tags=["health"], summary="存活检查（public）")
    async def healthz() -> dict[str, Any]:
        return {"code": 0, "message": "ok", "data": {"status": "ok"}}

    @app.get("/readyz", tags=["health"], summary="就绪检查（public）")
    async def readyz(request: Request) -> JSONResponse:
        checks: dict[str, str] = {}
        try:
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:
            logger.warning("readyz: 数据库不可用", exc_info=True)
            checks["database"] = "fail"
        try:
            await get_redis().ping()
            checks["redis"] = "ok"
        except Exception:
            logger.warning("readyz: Redis 不可用", exc_info=True)
            checks["redis"] = "fail"
        if all(v == "ok" for v in checks.values()):
            return _json(200, 0, "ok", checks, _request_id_of(request))
        code, message = CommonErrors.DEPENDENCY_UNAVAILABLE
        return _json(503, code, message, checks, _request_id_of(request))


def create_app(
    settings: BaseServiceSettings,
    routers: Sequence[APIRouter] = (),
    lifespan_hooks: Sequence[LifespanHook] = (),
    *,
    title: str | None = None,
    version: str = "0.1.0",
) -> FastAPI:
    """创建服务 app。

    ``routers`` 自带完整前缀；``lifespan_hooks`` 是 ``(app) -> async context manager`` 的列表，
    在 DB/Redis 初始化之后按序进入、关闭时逆序退出（用于启动后台消费者、定时任务等）。
    """
    setup_logging(settings.SERVICE_NAME, settings.LOG_LEVEL)
    try:
        settings.validate_for_runtime()
    except Exception:
        logger.critical("配置校验失败，拒绝启动", exc_info=True)
        raise

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_db(settings)
        init_redis(settings)
        auth_runtime.configure(settings)
        try:
            async with AsyncExitStack() as stack:
                for hook in lifespan_hooks:
                    await stack.enter_async_context(hook(app))
                yield
        finally:
            await auth_runtime.shutdown()
            await close_redis()
            await dispose_db()

    app = FastAPI(title=title or f"{settings.SERVICE_NAME} service", version=version, lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(InputGuardMiddleware)  # 先添加 = 更靠内；被拒绝的请求仍有 request id 与访问日志
    app.add_middleware(RequestContextMiddleware, trusted_proxies=settings.TRUSTED_PROXIES)
    register_exception_handlers(app)
    _register_health(app)
    for router in routers:
        app.include_router(router)
    return app
