"""kb 服务配置：继承共享库基类，所有项带本地开发默认值，可被 .env / 环境变量覆盖。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet

from platform_common.config import RELAXED_ENVS, BaseServiceSettings

# 仅供本地开发/测试使用的固定 Fernet key（base64 of 32 bytes）；生产必须通过环境变量覆盖
DEFAULT_MODEL_SECRET_KEY = "a2JwLWRldi1tb2RlbC1zZWNyZXQta2V5LTMyYnl0ZXM="
APP_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseServiceSettings):
    SERVICE_NAME: str = "kb"
    PORT: int = 8302

    S3_ENDPOINT: str = "http://127.0.0.1:19000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET: str = "kbp-files"
    S3_REGION: str = "us-east-1"

    MODEL_SECRET_KEY: str = DEFAULT_MODEL_SECRET_KEY  # 模型凭据 Fernet 密钥；生产必须覆盖

    UPLOAD_MAX_BYTES: int = 15 * 1024 * 1024
    DATASET_MAX_DOCUMENTS: int = 10000
    UPLOAD_FILE_TTL_HOURS: int = 24
    PARSE_PROCESS_WORKERS: int = 2  # 解析/校验进程池大小（同时限制并发解析数；超时的任务仍会占用池进程直到结束）
    PARSE_TIMEOUT_SECONDS: int = 60  # 单次校验/解析等待上限；超时返回 400504（文件解析超时）
    WORKER_CONCURRENCY: int = 4
    EMBED_BATCH_SIZE: int = 16
    MODEL_HTTP_TIMEOUT_SECONDS: float = 30.0
    PROCESS_TIMEOUT_MINUTES: int = 30  # 解析中/分段中/索引中无进度变化超过该时长 → 失败（处理超时）
    QUEUED_REDELIVER_MINUTES: int = 30  # 排队中超过该时长且队列里没有对应消息 → 重新投递（不计入处理超时）
    SWEEP_INTERVAL_SECONDS: int = 60  # 超时/排队巡检间隔
    UPLOAD_CLEANUP_INTERVAL_SECONDS: int = 3600  # 过期上传文件清理间隔
    TASK_CLAIM_IDLE_SECONDS: int = 600  # 他人遗留的未确认任务空闲多久后被接管
    DOC_LOCK_TTL_SECONDS: int = 90  # 单文档处理锁（带心跳续期），防止同一任务被重复并发处理
    REF_RECONCILE_INTERVAL_SECONDS: int = 600
    HIT_FLUSH_INTERVAL_SECONDS: int = 60
    QUERY_EMBED_CACHE_SECONDS: int = 600
    RETRIEVAL_CANDIDATE_MAX: int = 100
    JIEBA_USER_DICT: str = ""
    FULLTEXT_DROP_STOPWORDS: bool = True  # 全文检索查询去掉高频虚词（压测结论：否则最坏情况单次 >1s）

    # 检索性能（BE-21b，tech-design-m2 3.10.7）
    DB_POOL_SIZE: int = 20  # 覆盖共享默认 10：混合检索每请求最多占 2 条连接
    VECTOR_EXACT_MAX_ROWS: int = 20000  # 检索单元数 <= 该值走精确路径
    HNSW_EF_SEARCH: int = 200  # 查询时 hnsw.ef_search（实际取 max(该值, limit)，上限 1000）；压测从 100 调到 200
    HNSW_MAX_SCAN_TUPLES_MIN: int = 20000  # iterative scan 扫描上限的夹取范围
    HNSW_MAX_SCAN_TUPLES_MAX: int = 200000
    HNSW_M: int = 16  # 仅影响新建索引
    HNSW_EF_CONSTRUCTION: int = 128  # 仅影响新建索引；压测从 64 调到 128
    VECTOR_INDEX_RECONCILE_SECONDS: int = 600  # HNSW 索引对账周期
    FULLTEXT_PRUNE_MIN_ROWS: int = 20000  # 检索单元数超过才做全文候选裁剪
    FULLTEXT_COMMON_TERM_RATIO: float = 0.15  # 文档频率占比超过该值的词视为常见词；压测从 0.05 调到 0.15
    FULLTEXT_CANDIDATE_CAP: int = 10000  # 打分候选上限；压测从 3000 调到 10000
    FULLTEXT_COMMON_TERMS_REFRESH_SECONDS: int = 21600  # 常见词表刷新周期

    def validate_for_runtime(self) -> None:
        super().validate_for_runtime()
        if self.APP_ENV not in RELAXED_ENVS and self.MODEL_SECRET_KEY == DEFAULT_MODEL_SECRET_KEY:
            raise RuntimeError(f"APP_ENV={self.APP_ENV} 时必须覆盖配置项 MODEL_SECRET_KEY（不能使用开发默认值）")
        try:
            Fernet(self.MODEL_SECRET_KEY.encode())
        except (ValueError, TypeError) as exc:
            raise RuntimeError("MODEL_SECRET_KEY 不是合法的 Fernet key（32 字节 urlsafe base64）") from exc

    @property
    def tiktoken_file(self) -> Path:
        return APP_DIR / "assets" / "cl100k_base.tiktoken"


@lru_cache
def get_settings() -> Settings:
    return Settings()
