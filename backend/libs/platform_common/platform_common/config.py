"""服务通用配置基类。各服务在 ``app/core/config.py`` 继承并给出 SERVICE_NAME / PORT 默认值。"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录：libs/platform_common/platform_common/config.py → parents[3]
BACKEND_DIR = Path(__file__).resolve().parents[3]


RELAXED_ENVS = frozenset({"dev", "test"})
DEFAULT_INTERNAL_API_TOKEN = "dev-internal-token-change-me"
MIN_INTERNAL_TOKEN_LENGTH = 32


class BaseServiceSettings(BaseSettings):
    APP_ENV: str = "dev"  # dev / test / prod
    SERVICE_NAME: str  # iam / kb / open（子类给默认值）
    HOST: str = "127.0.0.1"
    PORT: int  # 子类给默认值

    DATABASE_URL: str = "postgresql+asyncpg://kbp:kbp@localhost:15432/kbp"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT_SECONDS: float = 10.0  # 取连接等待上限；耗尽时返回 503001 而不是挂起 30 秒
    DB_POOL_RECYCLE_SECONDS: int = 1800
    REDIS_URL: str = "redis://localhost:16379/0"
    REDIS_MAX_CONNECTIONS: int = 100
    REDIS_POOL_TIMEOUT_SECONDS: float = 5.0  # 连接用尽时排队等待上限，超时按 Redis 不可用处理（503001）

    JWT_PUBLIC_KEY_FILE: str = str(BACKEND_DIR / ".secrets" / "jwt_public.pem")  # 相对路径按 backend/ 解析
    JWT_ISSUER: str = "kbp-iam"
    INTERNAL_API_TOKEN: str = DEFAULT_INTERNAL_API_TOKEN
    IAM_INTERNAL_URL: str = "http://127.0.0.1:8301"
    KB_INTERNAL_URL: str = "http://127.0.0.1:8302"
    OPEN_INTERNAL_URL: str = "http://127.0.0.1:8303"
    INTERNAL_HTTP_TIMEOUT_SECONDS: float = 10.0

    TRUSTED_PROXIES: list[str] = ["127.0.0.1/32", "::1/128"]
    AUTHZ_CTX_TTL_SECONDS: int = 600
    LOG_LEVEL: str = "INFO"
    TIMEZONE: str = "Asia/Shanghai"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def validate_for_runtime(self) -> None:
        """启动前的配置安全检查（create_app 调用）。

        APP_ENV 不在 {"dev", "test"} 时，INTERNAL_API_TOKEN 若为开发默认值或短于 32 位则拒绝启动。
        子类可重写并先调用 ``super().validate_for_runtime()`` 追加同类检查。
        """
        if self.APP_ENV in RELAXED_ENVS:
            return
        token = self.INTERNAL_API_TOKEN
        if token == DEFAULT_INTERNAL_API_TOKEN or len(token) < MIN_INTERNAL_TOKEN_LENGTH:
            raise RuntimeError(
                f"APP_ENV={self.APP_ENV} 时必须覆盖配置项 INTERNAL_API_TOKEN"
                f"（不能使用开发默认值，且长度不少于 {MIN_INTERNAL_TOKEN_LENGTH} 位）"
            )

    @property
    def jwt_public_key_path(self) -> Path:
        """公钥文件的绝对路径（相对路径按 backend/ 解析）。"""
        path = Path(self.JWT_PUBLIC_KEY_FILE)
        return path if path.is_absolute() else BACKEND_DIR / path
