"""open 服务常量：专属错误码（tech-design-m3 5.0，code = HTTP 状态 × 1000 + 序号，open 段 600~799）。"""

from __future__ import annotations

MAX_SCOPE_DATASETS = 50
MAX_IP_WHITELIST = 20
MAX_LOG_SPAN_DAYS = 90
DEFAULT_LOG_SPAN_DAYS = 7
STATS_WINDOW_DAYS = 7


class OpenErrors:
    """``raise BizError(*OpenErrors.KEY_NAME_EXISTS)``；带 data 时 ``BizError(*OpenErrors.X, data=...)``。"""

    KEY_INVALID = (401601, "密钥缺失或无效")
    KEY_DISABLED = (403601, "密钥已停用")
    KEY_EXPIRED = (403602, "密钥已过期")
    IP_NOT_ALLOWED = (403603, "IP 不在白名单")
    DATASET_NOT_FOUND = (404601, "知识库不存在或未授权")
    RATE_LIMITED = (429601, "调用超限，请下一分钟再试")
    MODEL_UNAVAILABLE = (503601, "模型服务不可用")
    DATASETS_OUT_OF_RANGE = (400601, "所选知识库不在您的可访问范围内")
    EXPIRES_IN_PAST = (400602, "过期时间必须晚于当前时间")
    IP_WHITELIST_INVALID = (400603, "IP 白名单格式不正确或超过 20 条")
    LOG_RANGE_TOO_LONG = (400604, "调用日志查询时间跨度不能超过 90 天")
    ADMIN_DISABLED_NO_TOGGLE = (403604, "密钥已被管理员停用，无法启用")
    ADMIN_DISABLED_NO_MODIFY = (403605, "密钥已被管理员停用，无法修改")
    KEY_NAME_EXISTS = (409601, "密钥名称已存在")
