"""数据权限统一实现（总体方案 3.6）。``data_scope_filter`` 与 ``in_data_scope`` 语义必须一致。"""

from __future__ import annotations

from sqlalchemy import ColumnElement, SQLColumnExpression, false, or_, true

from platform_common.auth.context import AuthContext

# 列参数允许可空列（如日志表的 company_id/dept_id）：NULL 不命中任何范围条件
ScopeColumn = SQLColumnExpression[int] | SQLColumnExpression[int | None]


def data_scope_filter(
    ctx: AuthContext,
    *,
    company_col: ScopeColumn,
    dept_col: ScopeColumn,
    owner_col: ScopeColumn,
) -> ColumnElement[bool]:
    """super_admin 或 all → true()；否则 OR(company IN company_ids, dept IN org_ids, owner = user_id[include_self])；
    三者皆空 → false()。列为 NULL 时不命中（仅 all/超管可见）。全部使用绑定参数。"""
    scope = ctx.data_scope
    if ctx.is_super_admin or scope.all:
        return true()
    conds: list[ColumnElement[bool]] = []
    if scope.company_ids:
        conds.append(company_col.in_(scope.company_ids))
    if scope.org_ids:
        conds.append(dept_col.in_(scope.org_ids))
    if scope.include_self:
        conds.append(owner_col == ctx.user_id)
    return or_(*conds) if conds else false()


def in_data_scope(
    ctx: AuthContext,
    *,
    company_id: int | None,
    dept_id: int | None,
    owner_id: int | None,
) -> bool:
    """对单条已加载数据做同样判断（写操作前校验，防止通过 ID 越权）。"""
    scope = ctx.data_scope
    if ctx.is_super_admin or scope.all:
        return True
    if company_id is not None and company_id in scope.company_ids:
        return True
    if dept_id is not None and dept_id in scope.org_ids:
        return True
    return scope.include_self and owner_id is not None and owner_id == ctx.user_id
