"""登录日志写入、操作日志入库、日志查询与保留期清理。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import ColumnElement, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SysLoginLog, SysOperationLog, SysOrg, SysUser
from platform_common.auth.context import AuthContext
from platform_common.auth.data_scope import data_scope_filter

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult


async def add_login_log(
    session: AsyncSession,
    *,
    username: str,
    user_id: int | None,
    company_id: int | None,
    dept_id: int | None,
    result: str,
    fail_reason: str | None,
    fail_message: str | None,
    ip: str | None,
    user_agent: str | None,
    login_at: datetime,
) -> SysLoginLog:
    row = SysLoginLog(
        username=username[:64],
        user_id=user_id,
        company_id=company_id,
        dept_id=dept_id,
        result=result,
        fail_reason=fail_reason,
        fail_message=fail_message,
        ip=ip,
        user_agent=user_agent[:500] if user_agent else None,
        login_at=login_at,
        created_by=user_id or 0,
        updated_by=user_id or 0,
    )
    session.add(row)
    await session.flush()
    return row


# --------------------------------------------------------------------------- BE-10 汇聚与查询

OPLOG_BATCH_DELETE = 5000


def _scope(ctx: AuthContext, model: type[SysLoginLog] | type[SysOperationLog]) -> ColumnElement[bool]:
    """数据权限条件。company_id/dept_id 可空（NULL 不命中，仅 ALL/超管可见）。"""
    return data_scope_filter(
        ctx,
        company_col=model.company_id,
        dept_col=model.dept_id,
        owner_col=model.created_by,
    )


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def insert_operation_log(session: AsyncSession, values: dict[str, Any]) -> bool:
    """幂等入库：event_id 冲突时忽略；返回是否真正插入。"""
    stmt = (
        pg_insert(SysOperationLog)
        .values(**values)
        .on_conflict_do_nothing(index_elements=[SysOperationLog.event_id])
        .returning(SysOperationLog.id)
    )
    return (await session.scalar(stmt)) is not None


async def get_org_name(session: AsyncSession, org_id: int) -> str | None:
    name: str | None = await session.scalar(select(SysOrg.name).where(SysOrg.id == org_id))
    return name


def _oplog_conds(
    ctx: AuthContext,
    *,
    start_time: datetime,
    end_time: datetime,
    operator: str | None,
    module: str | None,
    action: str | None,
    result: str | None,
) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = [
        _scope(ctx, SysOperationLog),
        SysOperationLog.occurred_at >= start_time,
        SysOperationLog.occurred_at <= end_time,
    ]
    if operator:
        conds.append(
            or_(
                SysOperationLog.operator_name.ilike(_like(operator), escape="\\"),
                SysOperationLog.operator_username.ilike(_like(operator), escape="\\"),
            )
        )
    if module:
        conds.append(SysOperationLog.module == module)
    if action:
        conds.append(SysOperationLog.action == action)
    if result:
        conds.append(SysOperationLog.result == result)
    return conds


async def page_operation_logs(
    session: AsyncSession,
    ctx: AuthContext,
    *,
    offset: int,
    limit: int,
    start_time: datetime,
    end_time: datetime,
    operator: str | None,
    module: str | None,
    action: str | None,
    result: str | None,
) -> tuple[list[SysOperationLog], int]:
    conds = _oplog_conds(
        ctx, start_time=start_time, end_time=end_time, operator=operator, module=module, action=action, result=result
    )
    total = await session.scalar(select(func.count()).select_from(SysOperationLog).where(*conds)) or 0
    stmt = (
        select(SysOperationLog)
        .where(*conds)
        .order_by(SysOperationLog.occurred_at.desc(), SysOperationLog.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all()), int(total)


async def get_operation_log(session: AsyncSession, ctx: AuthContext, log_id: int) -> SysOperationLog | None:
    stmt = select(SysOperationLog).where(
        SysOperationLog.id == log_id,
        _scope(ctx, SysOperationLog),
    )
    row: SysOperationLog | None = await session.scalar(stmt)
    return row


async def page_login_logs(
    session: AsyncSession,
    ctx: AuthContext,
    *,
    offset: int,
    limit: int,
    start_time: datetime,
    end_time: datetime,
    username: str | None,
    result: str | None,
    ip: str | None,
) -> tuple[list[tuple[SysLoginLog, str | None, str | None]], int]:
    """返回 (日志, 用户姓名, 公司名称) 三元组；一次联表查询，无 N+1。"""
    conds: list[ColumnElement[bool]] = [
        _scope(ctx, SysLoginLog),
        SysLoginLog.login_at >= start_time,
        SysLoginLog.login_at <= end_time,
    ]
    if username:
        conds.append(SysLoginLog.username.ilike(_like(username), escape="\\"))
    if result:
        conds.append(SysLoginLog.result == result)
    if ip:
        conds.append(SysLoginLog.ip == ip)
    total = await session.scalar(select(func.count()).select_from(SysLoginLog).where(*conds)) or 0
    stmt = (
        select(SysLoginLog, SysUser.name, SysOrg.name)
        .outerjoin(SysUser, SysUser.id == SysLoginLog.user_id)
        .outerjoin(SysOrg, SysOrg.id == SysLoginLog.company_id)
        .where(*conds)
        .order_by(SysLoginLog.login_at.desc(), SysLoginLog.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(r[0], r[1], r[2]) for r in rows], int(total)


async def delete_older_than(
    session: AsyncSession, model: type[SysLoginLog] | type[SysOperationLog], cutoff: datetime
) -> int:
    """物理删除一批（≤5000）早于 cutoff 的日志，返回删除行数（保留期策略，非业务删除）。"""
    time_col = SysLoginLog.login_at if model is SysLoginLog else SysOperationLog.occurred_at
    ids = select(model.id).where(time_col < cutoff).limit(OPLOG_BATCH_DELETE)
    result = cast("CursorResult[Any]", await session.execute(delete(model).where(model.id.in_(ids))))
    return result.rowcount or 0
