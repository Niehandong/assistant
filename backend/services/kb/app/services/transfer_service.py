"""知识库所有权转移（F-20，tech-design-m2 3.8）：管理员单个/批量转移、所有者自行转移，共用同一转移内核。

* 单事务；``SELECT ... FOR UPDATE`` 锁知识库行（批量按 id 升序加锁）；转移以提交时的状态为准。
* 接收人以 ``load_auth_context`` 判定（强一致）：不存在/停用/删除/组织链停用 → 400321。
* 管理员转移：接收人须在操作人数据范围内（``in_data_scope`` 对 company_id / org_id / user_id）。
* 所有者自行转移：接收人主组织须在所有者所属公司及其下属内（所属为集团节点则不限）。
* 更新 ``owner_id``、``company_id``、``dept_id``（接收人当时的组织）、``version+1``；分配记录不变。
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dataset
from app.repositories import admin_repo, assignment_repo, dataset_repo
from app.repositories.dataset_acl import get_permission_level, require_dataset
from app.schemas.admin import AdminDatasetItem, BatchTransferBody, BatchTransferResult, TransferBody
from app.schemas.dataset import DatasetDetail
from app.services import admin_service, dataset_service
from app.services.audit_log import log_dataset_event
from platform_common.auth.context import AuthContext, load_auth_context
from platform_common.auth.data_scope import in_data_scope
from platform_common.errors import BizError, CommonErrors
from platform_common.oplog import oplog_scope

ERR_RECEIVER_INVALID = (400321, "接收人不在可转移范围内或账号不可用")
ERR_ALREADY_OWNER = (400322, "接收人已是该知识库的所有者")
ERR_NAME_CONFLICT = (409321, "接收人已有同名知识库，请先改名")
UQ_DATASET_NAME = dataset_service.UQ_DATASET_NAME


def _conflict(items: list[Dataset]) -> BizError:
    return BizError(
        *ERR_NAME_CONFLICT,
        data={"conflicts": [{"dataset_id": d.id, "dataset_name": d.name} for d in items]},
    )


async def _receiver(receiver_user_id: int) -> AuthContext:
    rc = await load_auth_context(receiver_user_id)
    if rc is None or not rc.usable:
        raise BizError(*ERR_RECEIVER_INVALID)
    return rc


async def _check_admin_scope(ctx: AuthContext, rc: AuthContext) -> None:
    if not in_data_scope(ctx, company_id=rc.company_id, dept_id=rc.org_id, owner_id=rc.user_id):
        raise BizError(*ERR_RECEIVER_INVALID)


async def _check_owner_scope(session: AsyncSession, ctx: AuthContext, rc: AuthContext) -> None:
    company = await assignment_repo.get_org(session, ctx.company_id)
    is_group = company is not None and company.org_type == "group"
    if not await assignment_repo.org_in_scope(session, rc.org_id, ctx.company_id, is_group):
        raise BizError(*ERR_RECEIVER_INVALID)


async def _summaries(session: AsyncSession, d: Dataset, rc: AuthContext) -> tuple[dict[str, Any], dict[str, Any]]:
    """转移前后的摘要：原所有者→新所有者、原组织→新组织（须在修改前调用）。"""
    owners = await dataset_repo.owners_by_id(session, [d.owner_id])
    orgs = await dataset_repo.orgs_by_id(session, [d.company_id, d.dept_id, rc.company_id, rc.org_id])

    def org_name(oid: int) -> str:
        o = orgs.get(oid)
        return o.name if o else ""

    old = owners.get(d.owner_id)
    before = {
        "owner_id": d.owner_id,
        "owner_name": old.name if old else "未知用户",
        "company_id": d.company_id,
        "company_name": org_name(d.company_id),
        "dept_id": d.dept_id,
        "dept_name": org_name(d.dept_id),
    }
    after = {
        "owner_id": rc.user_id,
        "owner_name": rc.name,
        "company_id": rc.company_id,
        "company_name": org_name(rc.company_id),
        "dept_id": rc.org_id,
        "dept_name": org_name(rc.org_id),
    }
    return before, after


def _apply(d: Dataset, rc: AuthContext, operator_id: int) -> None:
    d.owner_id = rc.user_id
    d.company_id = rc.company_id
    d.dept_id = rc.org_id
    d.version += 1
    d.updated_by = operator_id


async def transfer(
    session: AsyncSession, dataset: Dataset, receiver: AuthContext, operator: AuthContext
) -> dict[str, Any]:
    """转移内核：``dataset`` 须已加锁且调用方已校验范围/版本/接收人可用；不 commit。返回日志摘要。"""
    if receiver.user_id == dataset.owner_id:
        raise BizError(*ERR_ALREADY_OWNER)
    if await dataset_repo.name_taken(session, receiver.user_id, dataset.name):
        raise _conflict([dataset])
    before, after = await _summaries(session, dataset, receiver)
    _apply(dataset, receiver, operator.user_id)
    return {"before": before, "after": after}


async def _commit(session: AsyncSession, conflicts: list[Dataset]) -> None:
    """并发下唯一索引兜底：同名冲突映射为 409321。"""
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if UQ_DATASET_NAME in str(getattr(exc.orig, "constraint_name", "") or exc.orig):
            raise _conflict(conflicts) from exc
        raise


# ---------------------------------------------------------------- 所有者自行转移


async def owner_transfer(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, body: TransferBody
) -> DatasetDetail:
    async with oplog_scope(
        request, ctx, module="dataset", action="transfer", target_type="dataset", target_id=dataset_id
    ) as h:
        d = await require_dataset(session, ctx, dataset_id, "owner", for_update=True)
        h.set_target(d.id, d.name)
        if d.version != body.version:
            raise BizError(*CommonErrors.VERSION_CONFLICT)
        rc = await _receiver(body.receiver_user_id)
        await _check_owner_scope(session, ctx, rc)
        h.summary = await transfer(session, d, rc, ctx)
        await _commit(session, [d])
        await session.refresh(d)
        # 调用者此后通常已无访问权（仅可能经分配保留）；无访问权时按只读展示基础信息
        level = await get_permission_level(session, ctx, d.id)
        return await dataset_service.build_detail(session, ctx, d, level or "read")


# ---------------------------------------------------------------- 管理员转移


async def admin_transfer(
    session: AsyncSession, ctx: AuthContext, request: Request, dataset_id: int, body: TransferBody
) -> AdminDatasetItem:
    async with oplog_scope(
        request, ctx, module="dataset", action="transfer", target_type="dataset", target_id=dataset_id
    ) as h:
        d = await admin_repo.get_visible(session, ctx, dataset_id, for_update=True)
        if d is None:
            raise BizError(*CommonErrors.NOT_FOUND)
        h.set_target(d.id, d.name)
        if d.version != body.version:
            raise BizError(*CommonErrors.VERSION_CONFLICT)
        rc = await _receiver(body.receiver_user_id)
        await _check_admin_scope(ctx, rc)
        h.summary = await transfer(session, d, rc, ctx)
        await _commit(session, [d])
        await session.refresh(d)
        return (await admin_service.build_items(session, [d]))[0]


async def admin_batch_transfer(
    session: AsyncSession, ctx: AuthContext, request: Request, body: BatchTransferBody
) -> BatchTransferResult:
    # 成功时每个知识库单独记一条日志；失败只记一条 failure
    async with oplog_scope(request, ctx, module="dataset", action="transfer", target_type="dataset") as h:
        h.suppress = True
        rc = await _receiver(body.receiver_user_id)
        await _check_admin_scope(ctx, rc)
        if body.from_user_id == rc.user_id:
            raise BizError(*ERR_ALREADY_OWNER)
        datasets = await admin_repo.lock_visible_owned_by(session, ctx, body.from_user_id, body.dataset_ids)
        if body.dataset_ids is not None and {d.id for d in datasets} != set(body.dataset_ids):
            raise BizError(*CommonErrors.NOT_FOUND)  # 含范围外/非 from_user 名下/已删除的 id
        taken = await dataset_repo.taken_names(session, rc.user_id, [d.name for d in datasets])
        conflicts = [d for d in datasets if d.name in taken]
        if conflicts:
            raise _conflict(conflicts)
        logs: list[tuple[Dataset, dict[str, Any]]] = []
        for d in datasets:
            before, after = await _summaries(session, d, rc)
            _apply(d, rc, ctx.user_id)
            logs.append((d, {"before": before, "after": after, "batch": True}))
        await _commit(session, datasets)
        for d, summary in logs:
            await log_dataset_event(request, ctx, "transfer", d.id, d.name, summary)
        return BatchTransferResult(transferred=len(datasets))
