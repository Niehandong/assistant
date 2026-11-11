"""iam 服务配置：继承共享库基类，所有项带本地开发默认值，可被 .env / 环境变量覆盖。"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from platform_common.config import BACKEND_DIR, BaseServiceSettings


class Settings(BaseServiceSettings):
    SERVICE_NAME: str = "iam"
    PORT: int = 8301

    JWT_PRIVATE_KEY_FILE: str = str(BACKEND_DIR / ".secrets" / "jwt_private.pem")  # 相对路径按 backend/ 解析
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    LOGIN_MAX_FAILURES: int = 5
    LOGIN_FAIL_WINDOW_SECONDS: int = 900
    LOGIN_LOCK_SECONDS: int = 900

    SEED_ADMIN_PASSWORD: str = "Admin12345"
    SEED_GROUP_NAME: str = "集团"
    SEED_GROUP_CODE: str = "GROUP"

    LOG_RETENTION_DAYS: int = 180
    LOG_JOBS_ENABLED: bool = True  # 操作日志消费者与清理任务；单测中关闭
    KB_STATS_ENABLED: bool = False
    OPEN_STATS_ENABLED: bool = False

    def validate_for_runtime(self) -> None:
        super().validate_for_runtime()
        if self.APP_ENV not in ("dev", "test") and self.SEED_ADMIN_PASSWORD == "Admin12345":
            logging.getLogger(__name__).warning("SEED_ADMIN_PASSWORD 仍为默认值，生产环境请务必修改")

    @property
    def jwt_private_key_path(self) -> Path:
        path = Path(self.JWT_PRIVATE_KEY_FILE)
        return path if path.is_absolute() else BACKEND_DIR / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
