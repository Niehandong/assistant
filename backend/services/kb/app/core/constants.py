"""kb 业务常量（状态、类型枚举值）。"""

from __future__ import annotations

from enum import StrEnum

from platform_common.events.streams import STREAM_KB_TASKS


class ModelType(StrEnum):
    EMBEDDING = "embedding"
    RERANK = "rerank"


class ModelStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class ChunkMode(StrEnum):
    GENERAL = "general"
    PARENT_CHILD = "parent_child"


class DocStatus(StrEnum):
    QUEUED = "queued"
    PARSING = "parsing"
    SPLITTING = "splitting"
    INDEXING = "indexing"
    AVAILABLE = "available"
    FAILED = "failed"


class SegmentType(StrEnum):
    GENERAL = "general"
    PARENT = "parent"


class IndexStatus(StrEnum):
    PENDING = "pending"
    INDEXED = "indexed"
    UPDATING = "updating"
    FAILED = "failed"


class Permission(StrEnum):
    READ = "read"
    EDIT = "edit"


class TargetType(StrEnum):
    USER = "user"
    DEPT = "dept"
    COMPANY = "company"


TASK_STREAM = STREAM_KB_TASKS
DEFAULT_RETRIEVAL_CONFIG: dict[str, object] = {
    "search_method": "vector",
    "top_k": 3,
    "score_threshold_enabled": False,
    "score_threshold": 0.5,
    "reranking_enable": False,
    "reranking_model_id": None,
    "hybrid_mode": "weighted",
    "vector_weight": 0.7,
}
