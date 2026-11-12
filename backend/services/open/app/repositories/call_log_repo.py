"""api_call_log 查询（BE-28；BE-26 审计复用 ``CallLogFilter`` + ``page_logs``）。

* 本人视图：``CallLogFilter(owner_id=当前用户)``，条件 ``created_by = owner_id``（含已删除密钥的日志）。
* 审计视图：``CallLogFilter(scope_ctx=ctx, include_unknown=...)``，条件由共享库 ``data_scope_filter`` 生成
  （列 ``company_id / dept_id / created_by``）；``include_unknown=True``（调用方须先用
  ``can_view_unknown_calls`` 判定能力，无能力时必须传 False）时变为 ``(范围条件) OR api_key_id IS NULL``。
* 其余筛选条件（时间、密钥、知识库、结果、创建人关键字）用 AND 叠加在上述范围条件之外。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApiCallLog, UserRef
from platform_common.auth.context import AuthContext
from platform_common.auth.data_scope import data_scope_filter

SUCCESS = "success"


def like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@dataclass
class CallLogFilter:
    start_time: datetime
    end_time: datetime
    api_key_id: int | None = None
    dataset_id: int | None = None
    result: str | None = None
    creator_keyword: str | None = None  # user_ref 姓名/账号模糊（审计）
    owner_id: int | None = None  # 本人视图：created_by = owner_id
    scope_ctx: AuthContext | None = None  # 审计视图：按数据范围过滤
    include_unknown: bool = False  # 审计视图：并上 api_key_id IS NULL（调用方须已判定能力）


def build_conditions(f: CallLogFilter) -> list[ColumnElement[bool]]:
    """生成 where 条件（全部绑定参数）。本人视图与审计视图二选一；两者都没给时返回恒假条件，避免无范围查询。"""
    conds: list[ColumnElement[bool]] = [ApiCallLog.called_at >= f.start_time, ApiCallLog.called_at <= f.end_time]
    if f.owner_id is not None:
        conds.append(ApiCallLog.created_by == f.owner_id)
    elif f.scope_ctx is not None:
        scope = data_scope_filter(
            f.scope_ctx,
            company_col=ApiCallLog.company_id,
            dept_col=ApiCallLog.dept_id,
            owner_col=ApiCallLog.created_by,
        )
        if f.include_unknown:
            conds.append(or_(scope, ApiCallLog.api_key_id.is_(None)))
        else:
            # ALL / 超管的范围条件恒真，会把无法识别密钥的行也带出来；默认视图须显式排除
            conds.append(and_(scope, ApiCallLog.api_key_id.is_not(None)))
    else:
        conds.append(ApiCallLog.id < 0)
    if f.api_key_id is not None:
        conds.append(ApiCallLog.api_key_id == f.api_key_id)
    if f.dataset_id is not None:
        conds.append(ApiCallLog.dataset_id == f.dataset_id)
    if f.result:
        conds.append(ApiCallLog.result == f.result)
    if f.creator_keyword:
        pat = like_pattern(f.creator_keyword)
        conds.append(
            ApiCallLog.created_by.in_(
                select(UserRef.id).where(
                    or_(UserRef.name.like(pat, escape="\\"), UserRef.username.like(pat, escape="\\"))
                )
            )
        )
    return conds


async def page_logs(
    session: AsyncSession, f: CallLogFilter, *, offset: int, limit: int
) -> tuple[list[ApiCallLog], int]:
    """分页查询，called_at 倒序（同刻按 id 倒序保证稳定）。"""
    conds = build_conditions(f)
    total = (await session.execute(select(func.count()).select_from(ApiCallLog).where(*conds))).scalar_one()
    rows = (
        await session.execute(
            select(ApiCallLog)
            .where(*conds)
            .order_by(ApiCallLog.called_at.desc(), ApiCallLog.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars()
    return list(rows.all()), int(total)


async def stats_7d(
    session: AsyncSession, key_ids: Sequence[int], *, now: datetime | None = None
) -> dict[int, tuple[int, int]]:
    """近 7 天每个密钥的 (调用数, 失败数)；失败 = result <> 'success'。没有记录的密钥不在结果里。

    使用索引 ``(api_key_id, called_at DESC)``；``now`` 仅供测试注入。
    """
    if not key_ids:
        return {}
    since = (now or datetime.now().astimezone()) - timedelta(days=7)
    stmt = (
        select(
            ApiCallLog.api_key_id,
            func.count(),
            func.count().filter(ApiCallLog.result != SUCCESS),
        )
        .where(and_(ApiCallLog.api_key_id.in_(list(key_ids)), ApiCallLog.called_at >= since))
        .group_by(ApiCallLog.api_key_id)
    )
    return {int(k): (int(c), int(f)) for k, c, f in (await session.execute(stmt)).all() if k is not None}


async def delete_expired_batch(session: AsyncSession, cutoff: datetime, batch: int) -> int:
    """物理删除 ``called_at < cutoff`` 的一批记录，返回删除行数（调用方循环直到 0，并自行提交）。"""
    ids = select(ApiCallLog.id).where(ApiCallLog.called_at < cutoff).order_by(ApiCallLog.id).limit(batch)
    result = await session.execute(
        delete(ApiCallLog).where(ApiCallLog.id.in_(ids)).execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
