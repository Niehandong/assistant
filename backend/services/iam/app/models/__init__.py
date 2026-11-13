"""导入全部模型，保证 Alembic autogenerate 能看到所有表。"""

from app.models.log import SysLoginLog, SysOperationLog
from app.models.org import SCHEMA, SysOrg
from app.models.permission import SysPermission
from app.models.role import SysRole, SysRoleOrg, SysRolePermission, SysUserRole
from app.models.session import SysUserSession
from app.models.user import SysUser

__all__ = [
    "SCHEMA",
    "SysLoginLog",
    "SysOperationLog",
    "SysOrg",
    "SysPermission",
    "SysRole",
    "SysRoleOrg",
    "SysRolePermission",
    "SysUser",
    "SysUserRole",
    "SysUserSession",
]
