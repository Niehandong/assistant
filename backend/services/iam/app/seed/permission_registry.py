"""权限注册表：权限点的唯一来源（总体方案第 7 节），由 ``python -m app.seed`` 幂等写入。

新服务/新模块增加权限点时只改此文件。接口权限复用菜单/按钮权限码。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.constants import BuiltinRole, PermType

SA = BuiltinRole.SUPER_ADMIN
GA = BuiltinRole.GROUP_ADMIN
CA = BuiltinRole.COMPANY_ADMIN
EM = BuiltinRole.EMPLOYEE

ALL_ROLES: tuple[BuiltinRole, ...] = (SA, GA, CA, EM)
ADMIN_ROLES: tuple[BuiltinRole, ...] = (SA, GA, CA)  # 不含普通员工
GROUP_ONLY_ROLES: tuple[BuiltinRole, ...] = (SA, GA)  # 不含公司管理员（模型配置）


@dataclass(frozen=True)
class PermissionDef:
    code: str
    name: str
    perm_type: PermType
    parent_code: str | None
    path: str | None
    icon: str | None
    sort_order: int
    service: str
    default_roles: tuple[BuiltinRole, ...]


def _menu(
    code: str,
    name: str,
    parent: str | None,
    path: str,
    icon: str,
    sort: int,
    service: str,
    roles: tuple[BuiltinRole, ...],
) -> PermissionDef:
    return PermissionDef(code, name, PermType.MENU, parent, path, icon, sort, service, roles)


def _buttons(
    parent: str, service: str, roles: tuple[BuiltinRole, ...], items: list[tuple[str, str]]
) -> list[PermissionDef]:
    """按钮按给定顺序从 1 开始编号。"""
    return [
        PermissionDef(code, name, PermType.BUTTON, parent, None, None, idx, service, roles)
        for idx, (code, name) in enumerate(items, start=1)
    ]


# 注意：父级必须排在子级之前（seed 按顺序写入并解析 parent_id）
PERMISSIONS: list[PermissionDef] = [
    # ---- 知识库（kb） ----
    _menu("kb:dataset:list", "知识库", None, "/kb/datasets", "DatabaseOutlined", 1, "kb", ALL_ROLES),
    *_buttons(
        "kb:dataset:list",
        "kb",
        ALL_ROLES,
        [
            ("kb:dataset:create", "新建知识库"),
            ("kb:dataset:update", "编辑知识库设置/检索设置"),
            ("kb:dataset:delete", "删除知识库"),
            ("kb:dataset:assign", "管理分配"),
            ("kb:dataset:transfer", "转移自己的知识库"),
            ("kb:document:upload", "上传文档"),
            ("kb:document:update", "文档启停/重新分段/重试"),
            ("kb:document:delete", "删除文档"),
            ("kb:document:download", "下载原文件"),
            ("kb:segment:update", "分段编辑/新增/启停/删除"),
            ("kb:retrieval:test", "召回测试"),
        ],
    ),
    # ---- 开放平台（open） ----
    _menu("openapi:menu:root", "开放平台", None, "/openapi", "ApiOutlined", 2, "open", ALL_ROLES),
    _menu(
        "openapi:apikey:manage",
        "我的 API 密钥",
        "openapi:menu:root",
        "/openapi/keys",
        "KeyOutlined",
        1,
        "open",
        ALL_ROLES,
    ),
    _menu(
        "openapi:log:list", "调用日志", "openapi:menu:root", "/openapi/logs", "FileTextOutlined", 2, "open", ALL_ROLES
    ),
    _menu("openapi:doc:view", "API 文档", "openapi:menu:root", "/openapi/docs", "ReadOutlined", 3, "open", ALL_ROLES),
    # ---- 系统管理（iam 为主） ----
    _menu("system:menu:root", "系统管理", None, "/system", "SettingOutlined", 9, "iam", ADMIN_ROLES),
    _menu(
        "system:org:list", "组织管理", "system:menu:root", "/system/orgs", "ApartmentOutlined", 1, "iam", ADMIN_ROLES
    ),
    *_buttons(
        "system:org:list",
        "iam",
        ADMIN_ROLES,
        [
            ("system:org:create", "新增组织"),
            ("system:org:update", "编辑/移动/停用组织"),
            ("system:org:delete", "删除组织"),
        ],
    ),
    _menu("system:user:list", "用户管理", "system:menu:root", "/system/users", "UserOutlined", 2, "iam", ADMIN_ROLES),
    *_buttons(
        "system:user:list",
        "iam",
        ADMIN_ROLES,
        [
            ("system:user:create", "新增用户"),
            ("system:user:update", "编辑用户"),
            ("system:user:status", "停用/启用用户"),
            ("system:user:reset_pwd", "重置密码"),
            ("system:user:assign", "分配角色"),
            ("system:user:delete", "删除用户"),
        ],
    ),
    _menu("system:role:list", "角色管理", "system:menu:root", "/system/roles", "TeamOutlined", 3, "iam", ADMIN_ROLES),
    *_buttons(
        "system:role:list",
        "iam",
        ADMIN_ROLES,
        [
            ("system:role:create", "新增角色"),
            ("system:role:update", "编辑/停用角色"),
            ("system:role:grant", "分配权限与数据范围"),
            ("system:role:delete", "删除角色"),
        ],
    ),
    _menu(
        "kb:admin:list", "知识库管理", "system:menu:root", "/system/datasets", "AppstoreOutlined", 4, "kb", ADMIN_ROLES
    ),
    *_buttons(
        "kb:admin:list",
        "kb",
        ADMIN_ROLES,
        [
            ("kb:admin:view", "审计查看内容"),
            ("kb:admin:transfer", "转移所有权（管理员）"),
        ],
    ),
    _menu(
        "openapi:apikey:audit",
        "API 密钥审计",
        "system:menu:root",
        "/system/api-keys",
        "AuditOutlined",
        5,
        "open",
        ADMIN_ROLES,
    ),
    _menu(
        "system:model:list",
        "模型配置",
        "system:menu:root",
        "/system/models",
        "CloudServerOutlined",
        6,
        "kb",
        GROUP_ONLY_ROLES,
    ),
    *_buttons(
        "system:model:list",
        "kb",
        GROUP_ONLY_ROLES,
        [
            ("system:model:create", "新增模型"),
            ("system:model:update", "编辑/启停/设默认"),
            ("system:model:delete", "删除模型"),
        ],
    ),
    _menu("system:log:root", "日志", "system:menu:root", "/system/logs", "FileSearchOutlined", 7, "iam", ADMIN_ROLES),
    _menu(
        "system:oplog:list",
        "操作日志",
        "system:log:root",
        "/system/logs/operation",
        "HistoryOutlined",
        1,
        "iam",
        ADMIN_ROLES,
    ),
    _menu(
        "system:loginlog:list",
        "登录日志",
        "system:log:root",
        "/system/logs/login",
        "LoginOutlined",
        2,
        "iam",
        ADMIN_ROLES,
    ),
]

# 前端白名单（frontend/src/components/menuIcons.tsx 的 MENU_ICON_NAMES），新增图标需前后端同时登记
MENU_ICON_WHITELIST: frozenset[str] = frozenset(
    {
        "ApartmentOutlined", "ApiOutlined", "AppstoreOutlined", "AuditOutlined", "CloudServerOutlined",
        "DatabaseOutlined", "FileSearchOutlined", "FileTextOutlined", "HistoryOutlined", "KeyOutlined",
        "LoginOutlined", "ProfileOutlined", "ReadOutlined", "SafetyOutlined", "SettingOutlined",
        "TeamOutlined", "UserOutlined",
    }
)  # fmt: skip
