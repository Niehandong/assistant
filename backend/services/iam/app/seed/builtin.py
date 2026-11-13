"""内置角色定义（总体方案第 7 节）：4 个集团级内置角色。"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.constants import BuiltinRole, DataScopeType


@dataclass(frozen=True)
class BuiltinRoleDef:
    key: BuiltinRole
    code: str
    name: str
    data_scope: DataScopeType
    remark: str


BUILTIN_ROLES: list[BuiltinRoleDef] = [
    BuiltinRoleDef(
        BuiltinRole.SUPER_ADMIN, "super_admin", "超级管理员", DataScopeType.ALL, "内置：跳过所有权限与数据范围校验"
    ),
    BuiltinRoleDef(BuiltinRole.GROUP_ADMIN, "group_admin", "集团管理员", DataScopeType.ALL, "内置：集团级管理员"),
    BuiltinRoleDef(
        BuiltinRole.COMPANY_ADMIN,
        "company_admin",
        "公司管理员",
        DataScopeType.COMPANY_AND_CHILD,
        "内置：管理本公司及下属公司",
    ),
    BuiltinRoleDef(BuiltinRole.EMPLOYEE, "employee", "普通员工", DataScopeType.SELF, "内置：普通员工"),
]
