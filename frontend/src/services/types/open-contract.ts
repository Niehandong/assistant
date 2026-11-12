/**
 * open 服务接口契约类型（按 tech-design-m3.md 第 5 节手写）。
 * 后端 OpenAPI 就绪后，以 `pnpm gen:api` 生成到 src/services/types/open.d.ts 的类型为准，
 * 届时本文件应改为从生成类型派生并核对差异。
 */
import type { ApiResponse, PageResult } from './iam-contract';

export type { ApiResponse, PageResult };

// ---------- 5.0 错误码 ----------
export const OpenErrorCode = {
  DATASETS_OUT_OF_RANGE: 400601,
  EXPIRES_IN_PAST: 400602,
  IP_WHITELIST_INVALID: 400603,
  LOG_RANGE_TOO_LONG: 400604,
  ADMIN_DISABLED: 403604,
  ADMIN_DISABLED_MODIFY: 403605,
  KEY_NAME_EXISTS: 409601,
} as const;

/** 开放检索 API 错误码表（文档页展示，5.0） */
export interface OpenErrorRow {
  http: number;
  code: number;
  errorType: string;
  message: string;
  note?: string;
}

// ---------- 5.1 我的 API 密钥 ----------
export type ScopeType = 'all' | 'selected';
export type StoredStatus = 'enabled' | 'disabled' | 'admin_disabled';
/** 计算后的 6 种状态（3.2） */
export type KeyStatus = StoredStatus | 'owner_unavailable' | 'expired' | 'no_dataset';

export interface ApiKeyItem {
  id: number;
  name: string;
  description: string | null;
  key_masked: string;
  scope_type: ScopeType;
  /** scope_type=all 时为空数组 */
  dataset_ids: number[];
  accessible_dataset_count: number;
  status: KeyStatus;
  stored_status: StoredStatus;
  /** null = 永不过期 */
  expires_at: string | null;
  ip_whitelist: string[];
  rate_limit_per_min: number;
  calls_7d: number;
  failures_7d: number;
  last_used_at: string | null;
  created_at: string;
  version: number;
}

export interface ApiKeyListQuery {
  page?: number;
  page_size?: number;
  name?: string;
  status?: KeyStatus;
}

export interface ApiKeyBody {
  name: string;
  description?: string;
  scope_type: ScopeType;
  dataset_ids?: number[];
  expires_at: string | null;
  ip_whitelist: string[];
  rate_limit_per_min: number;
}

export interface ApiKeyUpdateBody extends ApiKeyBody {
  version: number;
}

/** 创建 / 重新生成的响应：明文只出现这一次 */
export interface ApiKeySecretResult {
  api_key: string;
  item: ApiKeyItem;
}

export interface ApiKeyStatusBody {
  status: 'enabled' | 'disabled';
  version: number;
}

export interface VersionBody {
  version: number;
}

export interface AccessibleDataset {
  id: number;
  name: string;
}

// ---------- 5.2 调用日志 ----------
export type CallResult =
  | 'success'
  | 'key_invalid'
  | 'key_disabled'
  | 'key_expired'
  | 'ip_not_allowed'
  | 'dataset_not_found'
  | 'invalid_params'
  | 'rate_limited'
  | 'model_unavailable'
  | 'service_unavailable'
  | 'internal_error';

export interface CallLogItem {
  id: number;
  called_at: string;
  request_id: string;
  /** 无法识别密钥时为 null */
  api_key: { id: number; name: string; key_masked: string } | null;
  dataset: { id: number; name: string | null } | null;
  query: string | null;
  result_count: number;
  latency_ms: number;
  result: CallResult;
  error_code: number | null;
  client_ip: string | null;
}

export interface AuditCallLogItem extends CallLogItem {
  creator: { id: number; name: string } | null;
}

export interface CallLogQuery {
  page?: number;
  page_size?: number;
  start_time?: string;
  end_time?: string;
  api_key_id?: number;
  dataset_id?: number;
  result?: CallResult;
}

export interface AuditCallLogQuery extends CallLogQuery {
  creator_keyword?: string;
  include_unknown?: boolean;
}

// ---------- 5.3 审计 ----------
export type AuditStatus =
  'enabled' | 'disabled' | 'admin_disabled' | 'expired' | 'owner_unavailable';

export interface AuditApiKeyItem extends Omit<ApiKeyItem, 'dataset_ids' | 'ip_whitelist'> {
  creator: { id: number; name: string; username: string; status: string };
  company: { id: number; name: string };
  dept: { id: number; name: string };
}

export interface AuditApiKeyQuery {
  page?: number;
  page_size?: number;
  creator_keyword?: string;
  org_id?: number;
  status?: AuditStatus;
}

/** 5.3 GET /audit/capabilities */
export interface AuditCapabilities {
  can_view_unknown_calls: boolean;
}
