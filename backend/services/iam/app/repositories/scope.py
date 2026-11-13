"""iam 的数据范围条件（技术方案 M1 5.2.0a）：管理范围与可见范围。

* **管理范围** ``manage_*``：共享库 ``data_scope_filter`` / ``in_data_scope`` 的原规则，所有写接口及写前校验使用；
* **可见范围** ``visible_*``：管理范围 OR SELF 只读特例（仅当持有 SELF 且无全局范围时追加）：
  用户 = 本人账号（``sys_user.id = ctx.user_id``），组织 = 本人组织链（``sys_org.id IN ctx.org_path``）。
  仅查询接口使用；命中"可见但不可管理"的写请求由 service 返回 403001。

共享库 ``data_scope_filter`` 语义不变，特例只在 iam 实现。
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, and_, or_

from app.models import SysOrg, SysUser
from platform_common.auth.context import AuthContext
from platform_common.auth.data_scope import data_scope_filter, in_data_scope


def _is_global(ctx: AuthContext) -> bool:
    return ctx.is_super_admin or ctx.data_scope.all


def manage_user_filter(ctx: AuthContext) -> ColumnElement[bool]:
    return data_scope_filter(
        ctx, company_col=SysUser.company_id, dept_col=SysUser.dept_id, owner_col=SysUser.created_by
    )


def visible_user_filter(ctx: AuthContext) -> ColumnElement[bool]:
    manage = manage_user_filter(ctx)
    if _is_global(ctx) or not ctx.data_scope.include_self:
        return manage
    return or_(manage, SysUser.id == ctx.user_id)


def manage_org_filter(ctx: AuthContext) -> ColumnElement[bool]:
    return data_scope_filter(ctx, company_col=SysOrg.company_id, dept_col=SysOrg.dept_id, owner_col=SysOrg.created_by)


def visible_org_filter(ctx: AuthContext) -> ColumnElement[bool]:
    manage = manage_org_filter(ctx)
    if _is_global(ctx) or not ctx.data_scope.include_self:
        return manage
    return or_(manage, and_(SysOrg.id.in_(list(ctx.org_path))))


def user_manageable(ctx: AuthContext, user: SysUser) -> bool:
    return in_data_scope(ctx, company_id=user.company_id, dept_id=user.dept_id, owner_id=user.created_by)


def user_visible(ctx: AuthContext, user: SysUser) -> bool:
    if user_manageable(ctx, user):
        return True
    return ctx.data_scope.include_self and user.id == ctx.user_id


def org_manageable(ctx: AuthContext, org: SysOrg) -> bool:
    return in_data_scope(ctx, company_id=org.company_id, dept_id=org.dept_id, owner_id=org.created_by)


def org_visible(ctx: AuthContext, org: SysOrg) -> bool:
    if org_manageable(ctx, org):
        return True
    return ctx.data_scope.include_self and org.id in ctx.org_path
