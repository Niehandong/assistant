"""权限/菜单相关 schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MenuNode(BaseModel):
    """`/auth/me` 的菜单树节点（5.1.4）。"""

    code: str
    name: str
    path: str | None
    icon: str | None
    sort_order: int
    children: list[MenuNode] = Field(default_factory=list)


class PermissionNode(BaseModel):
    """权限树节点（5.4.9）。`grantable` = 操作人拥有该权限（超管全部为 true）。"""

    id: int
    code: str
    name: str
    perm_type: str
    grantable: bool
    children: list[PermissionNode] = Field(default_factory=list)


class PermissionTreeData(BaseModel):
    tree: list[PermissionNode]
    max_data_scope: str
    can_custom: bool
