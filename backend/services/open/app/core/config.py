"""open 服务配置：继承共享库基类，所有项带本地开发默认值，可被 .env / 环境变量覆盖。"""

from __future__ import annotations

from functools import lru_cache

from platform_common.config import RELAXED_ENVS, BaseServiceSettings

# 仅供本地开发/测试使用的固定 HMAC 密钥；非 dev/test 环境必须通过环境变量覆盖。
# 注意：API_KEY_PEPPER 一旦在生产设置就不可更换，否则全部已发放的 API 密钥立即失效。
DEFAULT_API_KEY_PEPPER = "dev-api-key-pepper-change-me"


class Settings(BaseServiceSettings):
    SERVICE_NAME: str = "open"
    PORT: int = 8303

    API_KEY_PEPPER: str = DEFAULT_API_KEY_PEPPER  # HMAC-SHA256 密钥；生产必须覆盖且不可更换
    API_KEY_CACHE_SECONDS: int = 300  # 密钥记录缓存（变更时主动删除）
    KB_RETRIEVAL_URL: str = "http://127.0.0.1:8302"  # 可指向 kb 的"检索组"实例
    OPEN_RETRIEVE_TIMEOUT_SECONDS: float = 15.0  # 调 kb 内部检索的超时
    CALL_LOG_RETENTION_DAYS: int = 180
    CALL_LOG_CLEANUP_INTERVAL_SECONDS: int = 86400  # 保留期清理的执行间隔
    CALL_LOG_CLEANUP_BATCH: int = 5000  # 清理每批删除行数
    INVALID_KEY_LOG_PER_IP_PER_MIN: int = 20  # 无法识别密钥的调用日志按 IP 采样（TQ-04）
    REF_RECONCILE_INTERVAL_SECONDS: int = 600
    BACKGROUND_JOBS_ENABLED: bool = True  # 是否在进程内启动消费者/定时任务（测试可关闭）

    def validate_for_runtime(self) -> None:
        super().validate_for_runtime()
        if self.APP_ENV not in RELAXED_ENVS and (
            not self.API_KEY_PEPPER or self.API_KEY_PEPPER == DEFAULT_API_KEY_PEPPER
        ):
            raise RuntimeError(f"APP_ENV={self.APP_ENV} 时必须覆盖配置项 API_KEY_PEPPER（不能使用开发默认值）")


@lru_cache
def get_settings() -> Settings:
    return Settings()
