"""Redis key 规范（全平台统一，修改需走契约变更）。"""

from __future__ import annotations

AUTHZ_EPOCH = "authz:epoch"  # int，永久，全局失效版本号


def session(sid: str) -> str:
    return f"auth:sess:{sid}"  # JSON {"user_id","created_at"}，TTL 7 天，刷新续期


def user_sessions(user_id: int) -> str:
    return f"auth:user_sess:{user_id}"  # set(sid)，TTL 7 天


def login_fail(username: str) -> str:
    return f"auth:fail:{username}"  # int，TTL 900s


def login_lock(username: str) -> str:
    return f"auth:lock:{username}"  # string，TTL 900s


def authz_context(user_id: int) -> str:
    return f"authz:ctx:{user_id}"  # JSON AuthContext，TTL 600s


def job_lock(name: str) -> str:
    return f"job:lock:{name}"  # 单实例定时任务锁，TTL=任务间隔
