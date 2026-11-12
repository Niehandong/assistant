"""模型配置业务（F-07）：创建/编辑/启停/默认/删除、测试连接、凭据加密、引用检查。

约定：
* 凭据用 Fernet 加密入库，响应只含 ``api_key_hint``；操作日志摘要不含凭据。
* 需要联网测试时（启用、改连接信息），先结束读事务再发请求，避免长时间占用数据库连接；
  写入前重新加锁并校验 version（乐观锁 → 409001）。
* 测试连接单次不重试，总时限 ``TEST_TOTAL_TIMEOUT_SECONDS``（< 前端 60 秒超时）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.constants import TASK_STREAM, ModelType
from app.core.security import SecretDecryptError, decrypt_secret, encrypt_secret, make_key_hint
from app.model_clients.embedding import EmbeddingClient
from app.model_clients.errors import ModelBadResponse, ModelClientError, ModelHTTPError, ModelTimeout
from app.model_clients.rerank import RerankClient
from app.models import AiModel
from app.repositories import model_repo
from app.schemas.model import (
    ModelCreate,
    ModelDefaultBody,
    ModelItem,
    ModelOption,
    ModelStatusBody,
    ModelTestBody,
    ModelTestResult,
    ModelUpdate,
)
from platform_common.auth.context import AuthContext
from platform_common.errors import BizError, CommonErrors
from platform_common.events.publisher import publish_after_commit
from platform_common.oplog import oplog_scope
from platform_common.pagination import PageParams

logger = logging.getLogger(__name__)

ENABLED: str = "enabled"
DISABLED: str = "disabled"
TEST_TOTAL_TIMEOUT_SECONDS = 55.0  # 前端超时 60 秒，留出余量
TEST_TEXT = "连接测试"

ERR_TEST_FAILED = (400301, "模型连接测试未通过，不能启用")
ERR_NEED_DIMENSION = (400302, "Embedding 模型必须填写向量维度")
ERR_NEED_ENABLED = (400303, "请选择已启用的模型")
ERR_IN_USE_UPDATE = (409301, "模型已被知识库使用，不能修改服务地址、模型标识或维度")
ERR_IN_USE_DELETE = (409302, "模型已被知识库使用，不能删除")
ERR_DUP_NAME = (409304, "模型名称已存在")
TASK_ENSURE_INDEX = "vector.ensure_index"  # kb-worker 的 HNSW 索引创建/对账/清理任务（3.10.2）


def _enqueue_ensure_index(session: AsyncSession, model: AiModel) -> None:
    """Embedding 模型新建为启用 / 变为启用 / 改维度 / 删除后，提交后通知 worker 对账该模型的向量索引。"""
    if model.model_type == ModelType.EMBEDDING:
        publish_after_commit(session, TASK_STREAM, TASK_ENSURE_INDEX, {"model_id": model.id})


# ---------------------------------------------------------------- 测试连接


def _describe(exc: ModelClientError) -> str:
    if isinstance(exc, ModelTimeout):
        return "连接模型服务超时"
    if isinstance(exc, ModelHTTPError):
        return str(exc) if exc.status_code is None else f"模型服务返回错误（{exc}）"
    if isinstance(exc, ModelBadResponse):
        return f"模型服务响应不符合协议：{exc}"
    return "模型服务调用失败"


async def run_connection_test(
    model_type: str,
    base_url: str,
    model_name: str,
    api_key: str | None,
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ModelTestResult:
    """调用模型服务做连通性测试；从不抛出（失败以 success=false 返回），总耗时 ≤ TEST_TOTAL_TIMEOUT_SECONDS。"""
    s = settings or get_settings()
    timeout = min(s.MODEL_HTTP_TIMEOUT_SECONDS, TEST_TOTAL_TIMEOUT_SECONDS - 5)
    kwargs: dict[str, Any] = {"timeout": timeout, "transport": transport, "max_retries": 0}
    started = time.perf_counter()
    try:
        async with asyncio.timeout(TEST_TOTAL_TIMEOUT_SECONDS):
            if model_type == ModelType.EMBEDDING:
                vectors = await EmbeddingClient(base_url, model_name, api_key, **kwargs).embed([TEST_TEXT])
                dimension: int | None = len(vectors[0])
            else:
                results = await RerankClient(base_url, model_name, api_key, **kwargs).rerank(
                    TEST_TEXT, [TEST_TEXT], top_n=1
                )
                if not results:
                    raise ModelBadResponse("results 为空")
                dimension = None
    except TimeoutError:
        return ModelTestResult(success=False, error_message="连接模型服务超时")
    except ModelClientError as exc:
        return ModelTestResult(success=False, error_message=_describe(exc))
    except Exception:
        logger.error("模型连接测试异常", exc_info=True)
        return ModelTestResult(success=False, error_message="连接测试失败，请检查服务地址")
    latency = round((time.perf_counter() - started) * 1000)
    return ModelTestResult(success=True, dimension=dimension, latency_ms=latency)


def _decrypted_key(model: AiModel, settings: Settings) -> str | None:
    return decrypt_secret(model.api_key_encrypted, settings) if model.api_key_encrypted else None


async def test_endpoint(
    session: AsyncSession, body: ModelTestBody, settings: Settings | None = None
) -> ModelTestResult:
    """POST /models/test：``model_id`` 给出时，未提供的字段取已保存值（含凭据）。"""
    s = settings or get_settings()
    model_type, base_url, model_name, api_key = body.model_type, body.base_url, body.model_name, body.api_key
    if body.model_id is not None:
        model = await model_repo.get(session, body.model_id)
        if model is None:
            raise BizError(*CommonErrors.NOT_FOUND)
        model_type = model.model_type  # type: ignore[assignment]
        base_url = base_url or model.base_url
        model_name = model_name or model.model_name
        if api_key is None:
            try:
                api_key = _decrypted_key(model, s)
            except SecretDecryptError:
                return ModelTestResult(success=False, error_message="已保存的密钥无法解密，请重新填写")
    if not base_url or not model_name:
        raise BizError(
            CommonErrors.INVALID_PARAMS[0],
            "参数不合法",
            {"errors": [{"field": "base_url", "message": "服务地址与模型标识必填"}]},
        )
    await session.rollback()  # 结束读事务，释放连接后再联网
    return await run_connection_test(model_type, base_url, model_name, api_key or None, s)


async def _require_test_ok(
    model_type: str, base_url: str, model_name: str, api_key: str | None, dimension: int | None, settings: Settings
) -> ModelTestResult:
    result = await run_connection_test(model_type, base_url, model_name, api_key, settings)
    if not result.success:
        raise BizError(*ERR_TEST_FAILED, {"error_message": result.error_message})
    if model_type == ModelType.EMBEDDING and dimension is not None and result.dimension != dimension:
        raise BizError(
            *ERR_TEST_FAILED,
            {"error_message": f"模型返回的向量维度（{result.dimension}）与填写的维度（{dimension}）不一致"},
        )
    return result


# ---------------------------------------------------------------- 序列化与摘要


async def _items(session: AsyncSession, rows: Sequence[AiModel]) -> list[ModelItem]:
    counts = await model_repo.dataset_counts(session, rows)
    items = []
    for r in rows:
        item = ModelItem.model_validate(r)
        item.dataset_count = counts.get(r.id, 0)
        items.append(item)
    return items


def _snapshot(m: AiModel) -> dict[str, Any]:
    """操作日志用的字段快照：不含凭据与提示。"""
    return {
        "name": m.name,
        "model_type": m.model_type,
        "base_url": m.base_url,
        "model_name": m.model_name,
        "dimension": m.dimension,
        "max_input_tokens": m.max_input_tokens,
        "status": m.status,
        "is_default": m.is_default,
    }


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    keys = [k for k in after if before.get(k) != after[k]]
    return {"before": {k: before.get(k) for k in keys}, "after": {k: after[k] for k in keys}}


async def _in_use(session: AsyncSession, model: AiModel, err: tuple[int, str]) -> BizError:
    names, total = await model_repo.referencing_datasets(session, model)
    return BizError(*err, {"datasets": names, "total": total})


async def _commit(session: AsyncSession, model: AiModel | None = None) -> None:
    """提交；给出 model 时刷新（updated_at 等由数据库生成的列提交后会过期）。"""
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        constraint = str(getattr(exc.orig, "constraint_name", "") or exc.orig)
        if "uq_ai_model_name" in constraint:
            raise BizError(*ERR_DUP_NAME) from exc
        if "uq_ai_model_default" in constraint:
            raise BizError(*CommonErrors.VERSION_CONFLICT) from exc
        raise
    if model is not None:
        await session.refresh(model)


async def _locked(session: AsyncSession, model_id: int, version: int) -> AiModel:
    model = await model_repo.get(session, model_id, for_update=True)
    if model is None:
        raise BizError(*CommonErrors.NOT_FOUND)
    if model.version != version:
        raise BizError(*CommonErrors.VERSION_CONFLICT)
    return model


# ---------------------------------------------------------------- 查询


async def list_models(
    session: AsyncSession, pp: PageParams, *, model_type: str | None, status: str | None, keyword: str | None
) -> tuple[list[ModelItem], int]:
    rows, total = await model_repo.page_models(
        session, model_type=model_type, status=status, keyword=keyword, offset=pp.offset, limit=pp.limit
    )
    return await _items(session, rows), total


async def list_options(session: AsyncSession, model_type: str) -> list[ModelOption]:
    return [ModelOption.model_validate(m) for m in await model_repo.list_enabled(session, model_type)]


# ---------------------------------------------------------------- 写操作


def _normalize_embedding(model_type: str, dimension: int | None) -> int | None:
    if model_type == ModelType.EMBEDDING:
        if dimension is None:
            raise BizError(*ERR_NEED_DIMENSION)
        return dimension
    return None


async def create_model(session: AsyncSession, ctx: AuthContext, request: Request, body: ModelCreate) -> ModelItem:
    settings = get_settings()
    async with oplog_scope(
        request, ctx, module="model", action="create", target_type="model", target_name=body.name
    ) as h:
        dimension = _normalize_embedding(body.model_type, body.dimension)
        if body.is_default and body.status != ENABLED:
            raise BizError(*ERR_NEED_ENABLED)
        if await model_repo.name_exists(session, body.name):
            raise BizError(*ERR_DUP_NAME)
        api_key = body.api_key or None
        tested: ModelTestResult | None = None
        if body.status == ENABLED:
            tested = await _require_test_ok(
                body.model_type, body.base_url, body.model_name, api_key, dimension, settings
            )
        model = AiModel(
            name=body.name,
            model_type=body.model_type,
            base_url=body.base_url,
            model_name=body.model_name,
            api_key_encrypted=encrypt_secret(api_key, settings) if api_key else None,
            api_key_hint=make_key_hint(api_key) if api_key else None,
            dimension=dimension,
            max_input_tokens=body.max_input_tokens,
            status=body.status,
            is_default=False,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
        )
        if tested is not None:
            model.last_test_at, model.last_test_ok = datetime.now(UTC), True
        if body.is_default:
            await model_repo.clear_default(session, body.model_type, except_id=None, operator_id=ctx.user_id)
            model.is_default = True
        session.add(model)
        await session.flush()
        if body.status == ENABLED:
            _enqueue_ensure_index(session, model)
        await _commit(session, model)
        h.set_target(model.id, model.name)
        h.summary = {"after": {**_snapshot(model), "key_changed": bool(api_key)}}
        return (await _items(session, [model]))[0]


async def update_model(
    session: AsyncSession, ctx: AuthContext, request: Request, model_id: int, body: ModelUpdate
) -> ModelItem:
    settings = get_settings()
    async with oplog_scope(request, ctx, module="model", action="update", target_type="model", target_id=model_id) as h:
        model = await model_repo.get(session, model_id)
        if model is None:
            raise BizError(*CommonErrors.NOT_FOUND)
        h.set_target(model.id, model.name)
        before = _snapshot(model)
        dimension = _normalize_embedding(model.model_type, body.dimension)
        conn_changed = (
            body.base_url != model.base_url or body.model_name != model.model_name or dimension != model.dimension
        )
        if (
            model.model_type == ModelType.EMBEDDING
            and conn_changed
            and (await model_repo.referencing_datasets(session, model))[1]
        ):
            raise await _in_use(session, model, ERR_IN_USE_UPDATE)
        if await model_repo.name_exists(session, body.name, exclude_id=model_id):
            raise BizError(*ERR_DUP_NAME)

        new_status = body.status or model.status
        want_default = model.is_default if body.is_default is None else body.is_default
        if want_default and new_status != ENABLED:
            if body.is_default:  # 明确要求设为默认但模型未启用
                raise BizError(*ERR_NEED_ENABLED)
            want_default = False  # 被停用的默认模型自动取消默认

        if body.api_key is None:
            key_changed = False
            api_key = _decrypted_key_or_none(model, settings)
        else:
            key_changed = True
            api_key = body.api_key or None
        need_test = new_status == ENABLED and (conn_changed or key_changed or model.status != ENABLED)
        tested = False
        if need_test:
            mtype = model.model_type
            await session.rollback()  # 联网前释放连接（此后 ORM 对象已过期，只用局部变量）
            await _require_test_ok(mtype, body.base_url, body.model_name, api_key, dimension, settings)
            tested = True
        model = await _locked(session, model_id, body.version)
        model.name, model.base_url, model.model_name = body.name, body.base_url, body.model_name
        model.dimension, model.max_input_tokens, model.status = dimension, body.max_input_tokens, new_status
        if key_changed:
            model.api_key_encrypted = encrypt_secret(api_key, settings) if api_key else None
            model.api_key_hint = make_key_hint(api_key) if api_key else None
        if tested:
            model.last_test_at, model.last_test_ok = datetime.now(UTC), True
        if want_default and not model.is_default:
            await model_repo.clear_default(session, model.model_type, except_id=model.id, operator_id=ctx.user_id)
        model.is_default = want_default
        model.version += 1
        model.updated_by = ctx.user_id
        if before["dimension"] != model.dimension or (new_status == ENABLED and before["status"] != ENABLED):
            _enqueue_ensure_index(session, model)
        await _commit(session, model)
        summary = _diff(before, _snapshot(model))
        if key_changed:
            summary.setdefault("after", {})["key_changed"] = True
        h.summary = summary
        return (await _items(session, [model]))[0]


def _decrypted_key_or_none(model: AiModel, settings: Settings) -> str | None:
    try:
        return _decrypted_key(model, settings)
    except SecretDecryptError:
        return None


async def set_status(
    session: AsyncSession, ctx: AuthContext, request: Request, model_id: int, body: ModelStatusBody
) -> ModelItem:
    settings = get_settings()
    async with oplog_scope(request, ctx, module="model", action="status", target_type="model", target_id=model_id) as h:
        model = await model_repo.get(session, model_id)
        if model is None:
            raise BizError(*CommonErrors.NOT_FOUND)
        h.set_target(model.id, model.name)
        before_status = model.status
        tested = False
        if body.status == ENABLED:
            base_url, model_name, dimension, mtype = model.base_url, model.model_name, model.dimension, model.model_type
            api_key = _decrypted_key_or_none(model, settings)
            await session.rollback()
            await _require_test_ok(mtype, base_url, model_name, api_key, dimension, settings)
            tested = True
        model = await _locked(session, model_id, body.version)
        model.status = body.status
        cleared_default = False
        if body.status == DISABLED and model.is_default:
            model.is_default, cleared_default = False, True
        if tested:
            model.last_test_at, model.last_test_ok = datetime.now(UTC), True
        model.version += 1
        model.updated_by = ctx.user_id
        if body.status == ENABLED and before_status != ENABLED:
            _enqueue_ensure_index(session, model)
        await _commit(session, model)
        h.summary = {"before": {"status": before_status}, "after": {"status": model.status}}
        if cleared_default:
            h.summary["default_cleared"] = True
        return (await _items(session, [model]))[0]


async def set_default(
    session: AsyncSession, ctx: AuthContext, request: Request, model_id: int, body: ModelDefaultBody
) -> ModelItem:
    async with oplog_scope(
        request, ctx, module="model", action="set_default", target_type="model", target_id=model_id
    ) as h:
        model = await _locked(session, model_id, body.version)
        h.set_target(model.id, model.name)
        if model.status != ENABLED:
            raise BizError(*ERR_NEED_ENABLED)
        if not model.is_default:
            await model_repo.clear_default(session, model.model_type, except_id=model.id, operator_id=ctx.user_id)
            model.is_default = True
            model.version += 1
            model.updated_by = ctx.user_id
            await _commit(session, model)
        else:
            h.suppress = True  # 已是默认：无变更，不记日志
        h.summary = {"after": {"model_type": model.model_type, "is_default": True}}
        return (await _items(session, [model]))[0]


async def delete_model(session: AsyncSession, ctx: AuthContext, request: Request, model_id: int) -> None:
    async with oplog_scope(request, ctx, module="model", action="delete", target_type="model", target_id=model_id) as h:
        model = await model_repo.get(session, model_id, for_update=True)
        if model is None:
            raise BizError(*CommonErrors.NOT_FOUND)
        h.set_target(model.id, model.name)
        if (await model_repo.referencing_datasets(session, model))[1]:
            raise await _in_use(session, model, ERR_IN_USE_DELETE)
        h.summary = {"before": _snapshot(model)}
        model.is_deleted = True
        model.is_default = False
        model.updated_by = ctx.user_id
        model.version += 1
        _enqueue_ensure_index(session, model)  # 模型已删除：worker 对账时删除其 HNSW 索引
        await _commit(session)
