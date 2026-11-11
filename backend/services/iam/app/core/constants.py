"""iam 领域常量（取值与技术方案 M1 第 4、5.8 节一致）。"""

from __future__ import annotations

from enum import StrEnum


class OrgType(StrEnum):
    GROUP = "group"
    COMPANY = "company"
    DEPT = "dept"


class Status(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class RoleType(StrEnum):
    GROUP = "group"
    COMPANY = "company"


class DataScopeType(StrEnum):
    ALL = "ALL"
    COMPANY_AND_CHILD = "COMPANY_AND_CHILD"
    COMPANY = "COMPANY"
    DEPT_AND_CHILD = "DEPT_AND_CHILD"
    DEPT = "DEPT"
    SELF = "SELF"
    CUSTOM = "CUSTOM"


class PermType(StrEnum):
    MENU = "menu"
    BUTTON = "button"
    API = "api"


class BuiltinRole(StrEnum):
    SUPER_ADMIN = "super_admin"
    GROUP_ADMIN = "group_admin"
    COMPANY_ADMIN = "company_admin"
    EMPLOYEE = "employee"


class RevokeReason(StrEnum):
    LOGOUT = "logout"
    PASSWORD_CHANGED = "password_changed"
    PASSWORD_RESET = "password_reset"
    USER_DISABLED = "user_disabled"
    USER_DELETED = "user_deleted"
    ORG_DISABLED = "org_disabled"


class LoginFailReason(StrEnum):
    BAD_CREDENTIALS = "bad_credentials"
    LOCKED = "locked"
    USER_DISABLED = "user_disabled"
    ORG_DISABLED = "org_disabled"


class LoginResult(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


ROOT_PARENT_ID = 0
ADMIN_USERNAME = "admin"
ADMIN_NAME = "系统管理员"
PASSWORD_PATTERN = r"^(?=.*[A-Za-z])(?=.*\d).{8,32}$"
USERNAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{3,31}$"
