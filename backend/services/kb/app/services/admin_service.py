"""知识库管理视图（F-20，tech-design-m2 5.8、5.8.1）：按数据范围只读审计。

* 数据范围：``admin_repo.visible_cond``（``data_scope_filter``，company_id / dept_id / owner_id）；
  不在范围内或不存在一律 404000。独立于日常 ACL，不会让管理员获得日常访问权。
* 审计日志（dataset/admin_view）：``audit_entry=true`` 或 30 分钟窗口内同一操作人对同一对象首次访问才记录；
  Redis 不可用时按"记录"处理（审计不可被绕过）。文档列表/详情不记录。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dataset, UserRef
from app.repositories import admin_repo, dataset_repo
from app.repositories.admin_repo import AdminFilter
from app.repositories.document_repo import DocumentFilter
from app.schemas.admin import (
    AdminDatasetDetail,
    AdminDatasetItem,
    AdminOwner,
    AdminOwnerOption,
    OrgBrief,
)
from app.schemas.assignment import AssignableUser
from app.schemas.dataset import RetrievalConfig
from app.schemas.document import DocumentDetail, DocumentItem
from app.schemas.segment import SegmentItem
from app.services import assignment_service, document_service, segment_service
from app.services.audit_log import log_dataset_event
from app.services.dataset_service import _model_brief
from platform_common.auth.context import AuthContext
from platform_common.errors import BizError, CommonErrors
from platform_common.pagination import PageParams
from platform_common.redis import get_redis

logger = logging.getLogger(__name__)

AUDIT_WINDOW_SECONDS = 1800
MAX_OWNERS = 50


def audit_key(user_id: int, kind: str, obj_id: int) -> str:
    return f"kb:audit:{user_id}:{kind}:{obj_id}"


async def should_audit(user_id: int, kind: str, obj_id: int, audit_entry: bool) -> bool:
    """5.8.1：主动进入（audit_entry）必记并刷新去重 key；否则仅 key 首次写入成功时记。"""
    key = audit_key(user_id, kind, obj_id)
    try:
        r = get_redis()
        if audit_entry:
            await r.set(key, "1", ex=AUDIT_WINDOW_SECONDS)
            return True
        return bool(await r.set(key, "1", nx=True, ex=AUDIT_WINDOW_SECONDS))
    except Exception:
        logger.error("审计去重 Redis 不可用，按记录处理", exc_info=True)
        return True


# ---------------------------------------------------------------- 序列化


def _owner(owner_id: int, users: dict[int, UserRef]) -> AdminOwner:
    u = users.get(owner_id)
    if u is None:
        return AdminOwner(id=owner_id, name="未知用户", username="", status="deleted")
    return AdminOwner(id=u.id, name=u.name, username=u.username, status=admin_repo.owner_status_of(u))


async def build_items(session: AsyncSession, rows: Sequence[Dataset]) -> list[AdminDatasetItem]:
    users = await dataset_repo.owners_by_id(session, [d.owner_id for d in rows])
    orgs = await dataset_repo.orgs_by_id(session, [i for d in rows for i in (d.company_id, d.dept_id)])
    counts = await admin_repo.assignment_counts(session, [d.id for d in rows])

    def brief(oid: int) -> OrgBrief:
        o = orgs.get(oid)
        return OrgBrief(id=oid, name=o.name if o else "")

    return [
        AdminDatasetItem(
            id=d.id,
            name=d.name,
            owner=_owner(d.owner_id, users),
            company=brief(d.company_id),
            dept=brief(d.dept_id),
            chunk_mode=d.chunk_mode,  # type: ignore[arg-type]
            doc_count=d.doc_count,
            segment_count=d.segment_count,
            child_segment_count=d.child_segment_count,
            assignment_count=counts.get(d.id, 0),
            created_at=d.created_at,
            updated_at=d.updated_at,
            version=d.version,
        )
        for d in rows
    ]


async def _visible(session: AsyncSession, ctx: AuthContext, dataset_id: int) -> Dataset:
    d = await admin_repo.get_visible(session, ctx, dataset_id)
    if d is None:
        raise BizError(*CommonErrors.NOT_FOUND)
    return d


# ---------------------------------------------------------------- 查询


async def list_datasets(
    session: AsyncSession, ctx: AuthContext, f: AdminFilter, pp: PageParams
) -> tuple[list[AdminDatasetItem], int]:
    rows, total = await admin_repo.page_datasets(session, ctx, f, offset=pp.offset, limit=pp.limit)
    return await build_items(session, rows), total


async def get_dataset(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, audit_entry: bool
) -> AdminDatasetDetail:
    d = await _visible(session, ctx, dataset_id)
    item = (await build_items(session, [d]))[0]
    models = await dataset_repo.models_by_id(session, [d.embedding_model_id])
    detail = AdminDatasetDetail(
        **item.model_dump(),
        description=d.description,
        embedding_model=_model_brief(d.embedding_model_id, models),
        retrieval_config=RetrievalConfig.model_validate(d.retrieval_config),
        assignments=await assignment_service.list_for_dataset(session, d.id),
    )
    if await should_audit(ctx.user_id, "ds", d.id, audit_entry):
        await log_dataset_event(request, ctx, "admin_view", d.id, d.name, {})
    return detail


async def list_documents(
    session: AsyncSession, ctx: AuthContext, dataset_id: int, f: DocumentFilter, pp: PageParams
) -> tuple[list[DocumentItem], int]:
    await _visible(session, ctx, dataset_id)
    return await document_service.list_documents_unchecked(session, dataset_id, f, pp.offset, pp.limit)


async def get_document(session: AsyncSession, ctx: AuthContext, dataset_id: int, document_id: int) -> DocumentDetail:
    await _visible(session, ctx, dataset_id)
    return await document_service.get_detail_unchecked(session, dataset_id, document_id)


async def list_segments(
    session: AsyncSession,
    ctx: AuthContext,
    request: Request,
    dataset_id: int,
    document_id: int,
    *,
    keyword: str | None,
    enabled: bool | None,
    audit_entry: bool,
    pp: PageParams,
) -> tuple[list[SegmentItem], int]:
    d = await _visible(session, ctx, dataset_id)
    items, total = await segment_service.list_segments_unchecked(
        session, dataset_id, document_id, keyword=keyword, enabled=enabled, offset=pp.offset, limit=pp.limit
    )
    if await should_audit(ctx.user_id, "doc", document_id, audit_entry):
        doc = await document_service.get_detail_unchecked(session, dataset_id, document_id)
        await log_dataset_event(
            request, ctx, "admin_view", d.id, d.name, {"document_id": document_id, "document_name": doc.name}
        )
    return items, total


async def list_receivers(
    session: AsyncSession, ctx: AuthContext, keyword: str | None, pp: PageParams
) -> tuple[list[AssignableUser], int]:
    rows, total = await admin_repo.page_receivers(session, ctx, keyword, offset=pp.offset, limit=pp.limit)
    return [
        AssignableUser(id=u.id, username=u.username, name=u.name, org_name=org, company_name=comp)
        for u, org, comp in rows
    ], total


async def list_owners(session: AsyncSession, ctx: AuthContext, keyword: str | None) -> list[AdminOwnerOption]:
    rows = await admin_repo.list_owners(session, ctx, keyword, limit=MAX_OWNERS)
    return [
        AdminOwnerOption(
            id=oid,
            username=u.username if u else "",
            name=u.name if u else "未知用户",
            status=admin_repo.owner_status_of(u),
            dataset_count=cnt,
        )
        for oid, u, cnt in rows
    ]
