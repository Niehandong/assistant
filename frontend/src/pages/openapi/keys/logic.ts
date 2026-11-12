import dayjs, { type Dayjs } from 'dayjs';
import type { ApiKeyBody, ApiKeyItem, KeyStatus, ScopeType } from '@/services/types/open-contract';
import { ApiError, ErrorCode } from '@/utils/error';
import { OpenErrorCode } from '@/services/types/open-contract';

export const NAME_MAX = 50;
export const DESC_MAX = 200;
export const RATE_MIN = 1;
export const RATE_MAX = 600;
export const RATE_DEFAULT = 60;
export const DATASET_MIN = 1;
export const DATASET_MAX = 50;
export const IP_MAX = 20;

export const STATUS_LABEL: Record<KeyStatus, string> = {
  enabled: '启用',
  disabled: '已停用',
  admin_disabled: '已被管理员停用',
  expired: '已过期',
  owner_unavailable: '创建人不可用',
  no_dataset: '无可检索知识库',
};

export const STATUS_COLOR: Record<KeyStatus, string> = {
  enabled: 'success',
  disabled: 'default',
  admin_disabled: 'error',
  expired: 'warning',
  owner_unavailable: 'error',
  no_dataset: 'warning',
};

export const STATUS_OPTIONS = (Object.keys(STATUS_LABEL) as KeyStatus[]).map((k) => ({
  label: STATUS_LABEL[k],
  value: k,
}));

export function statusLabel(s: string): string {
  return STATUS_LABEL[s as KeyStatus] ?? s;
}

export const SCOPE_LABEL: Record<ScopeType, string> = {
  all: '我可访问的全部知识库',
  selected: '指定知识库',
};

/** 列表中的检索范围文案：全部可访问 / 指定 x 个 */
export function scopeText(item: Pick<ApiKeyItem, 'scope_type' | 'dataset_ids'>): string {
  return item.scope_type === 'all' ? '全部可访问' : `指定 ${item.dataset_ids.length} 个`;
}

/** 过期时间展示 */
export function expiresText(expiresAt: string | null, fmt = 'YYYY-MM-DD HH:mm:ss'): string {
  if (!expiresAt) return '永不过期';
  const d = dayjs(expiresAt);
  return d.isValid() ? d.format(fmt) : '-';
}

// ---------- 行操作可见性 ----------
export interface RowActions {
  edit: boolean;
  /** 停用 / 启用；被管理员停用时为 null（创建人不能自行启用，AC-72） */
  toggle: 'disable' | 'enable' | null;
  regenerate: boolean;
  remove: boolean;
  logs: boolean;
}

export const ADMIN_DISABLED_HINT = '已被管理员停用，无法修改或启用，可删除后新建';

/** 403604 / 403605：密钥已被管理员停用（需提示并刷新列表） */
export function isAdminDisabledError(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    (err.code === OpenErrorCode.ADMIN_DISABLED || err.code === OpenErrorCode.ADMIN_DISABLED_MODIFY)
  );
}

export function rowActions(item: Pick<ApiKeyItem, 'stored_status'>): RowActions {
  // admin_disabled 是终态：只保留删除与日志（5.1.0）
  if (item.stored_status === 'admin_disabled') {
    return { edit: false, toggle: null, regenerate: false, remove: true, logs: true };
  }
  let toggle: RowActions['toggle'] = null;
  if (item.stored_status === 'enabled') toggle = 'disable';
  else toggle = 'enable';
  return { edit: true, toggle, regenerate: true, remove: true, logs: true };
}

// ---------- 表单校验 ----------
const IPV4_RE = /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/;

/** IPv4 或 IPv4 CIDR（前缀 0~32） */
export function isValidIpOrCidr(text: string): boolean {
  const [ip, prefix, ...rest] = text.split('/');
  if (rest.length > 0 || !IPV4_RE.test(ip)) return false;
  if (prefix === undefined) return true;
  return /^\d{1,2}$/.test(prefix) && Number(prefix) <= 32;
}

/** 多行文本 -> 条目（按换行、英文逗号、中文逗号、空白拆分，去空、去重，保持顺序） */
export function splitIpText(text: string | undefined | null): string[] {
  const out: string[] = [];
  for (const raw of (text ?? '').split(/[\s,，;；]+/)) {
    const v = raw.trim();
    if (v && !out.includes(v)) out.push(v);
  }
  return out;
}

/** 校验 IP 白名单文本；通过返回 null，否则给出具体原因 */
export function validateIpText(text: string | undefined | null): string | null {
  const list = splitIpText(text);
  if (list.length > IP_MAX) return `最多 ${IP_MAX} 条，当前 ${list.length} 条`;
  const bad = list.filter((v) => !isValidIpOrCidr(v));
  if (bad.length > 0) {
    const shown = bad.slice(0, 3).join('、');
    return `格式不正确：${shown}${bad.length > 3 ? ' 等' : ''}（仅支持 IPv4 或 IPv4 网段，如 10.0.0.0/24）`;
  }
  return null;
}

/** 限流范围 1~600 的整数 */
export function validateRate(v: number | null | undefined): string | null {
  if (v === null || v === undefined || !Number.isInteger(v)) return '请输入整数';
  if (v < RATE_MIN || v > RATE_MAX) return `取值范围 ${RATE_MIN}~${RATE_MAX}`;
  return null;
}

/** 检索范围校验：指定模式须选 1~50 个知识库 */
export function validateScope(scope: ScopeType, ids: number[] | undefined): string | null {
  if (scope === 'all') return null;
  const n = new Set(ids ?? []).size;
  if (n < DATASET_MIN) return '请至少选择 1 个知识库';
  if (n > DATASET_MAX) return `最多选择 ${DATASET_MAX} 个知识库，当前 ${n} 个`;
  return null;
}

/** 过期日期：不得早于今天 */
export function isExpireDateDisabled(current: Dayjs, now: Dayjs = dayjs()): boolean {
  return current.endOf('day').isBefore(now);
}

/** 默认过期时间：当前日期 + 1 年 */
export function defaultExpireDate(now: Dayjs = dayjs()): Dayjs {
  return now.add(1, 'year').startOf('day');
}

/** 选中的日期 -> 当天 23:59:59（带时区偏移的 ISO） */
export function toExpiresIso(date: Dayjs | string | null | undefined): string | null {
  // ProForm 的 onFinish 可能把日期值转换为字符串，统一用 dayjs 解析
  return date ? dayjs(date).endOf('day').format() : null;
}

// ---------- 表单 <-> 请求体 ----------
export type ExpireMode = 'never' | 'date';

export interface KeyFormValues {
  name: string;
  description?: string;
  scope_type: ScopeType;
  dataset_ids?: number[];
  expire_mode: ExpireMode;
  expires_date?: Dayjs | string | null;
  ip_text?: string;
  rate_limit_per_min: number;
}

export function defaultFormValues(now: Dayjs = dayjs()): KeyFormValues {
  return {
    name: '',
    description: '',
    scope_type: 'all',
    dataset_ids: [],
    expire_mode: 'date',
    expires_date: defaultExpireDate(now),
    ip_text: '',
    rate_limit_per_min: RATE_DEFAULT,
  };
}

export function formValuesFromItem(item: ApiKeyItem): KeyFormValues {
  return {
    name: item.name,
    description: item.description ?? '',
    scope_type: item.scope_type,
    dataset_ids: item.dataset_ids,
    expire_mode: item.expires_at ? 'date' : 'never',
    expires_date: item.expires_at ? dayjs(item.expires_at) : defaultExpireDate(),
    ip_text: item.ip_whitelist.join('\n'),
    rate_limit_per_min: item.rate_limit_per_min,
  };
}

export function buildKeyBody(v: KeyFormValues): ApiKeyBody {
  const selected = v.scope_type === 'selected';
  return {
    name: v.name.trim(),
    description: v.description?.trim() ?? '',
    scope_type: v.scope_type,
    dataset_ids: selected ? [...new Set(v.dataset_ids ?? [])] : [],
    expires_at: v.expire_mode === 'never' ? null : toExpiresIso(v.expires_date),
    ip_whitelist: splitIpText(v.ip_text),
    rate_limit_per_min: v.rate_limit_per_min,
  };
}

// ---------- 后端错误 -> 表单字段 ----------
export interface FieldMessage {
  field: string;
  message: string;
}

const FIELD_MAP: Record<string, string> = {
  name: 'name',
  description: 'description',
  scope_type: 'scope_type',
  dataset_ids: 'dataset_ids',
  expires_at: 'expires_date',
  ip_whitelist: 'ip_text',
  rate_limit_per_min: 'rate_limit_per_min',
};

/** 把创建/编辑失败映射到字段；无法映射时返回 null，由调用方整体提示 */
export function mapSubmitError(err: unknown): FieldMessage[] | null {
  if (!(err instanceof ApiError)) return null;
  switch (err.code) {
    case OpenErrorCode.KEY_NAME_EXISTS:
      return [{ field: 'name', message: '该名称已存在，请换一个' }];
    case OpenErrorCode.DATASETS_OUT_OF_RANGE:
      return [{ field: 'dataset_ids', message: err.message }];
    case OpenErrorCode.EXPIRES_IN_PAST:
      return [{ field: 'expires_date', message: err.message }];
    case OpenErrorCode.IP_WHITELIST_INVALID:
      return [{ field: 'ip_text', message: err.message }];
    case ErrorCode.PARAM_INVALID: {
      const errors = (err.data as { errors?: { field: string; message: string }[] } | null)?.errors;
      const mapped = (errors ?? [])
        .filter((e) => FIELD_MAP[e.field])
        .map((e) => ({ field: FIELD_MAP[e.field], message: e.message }));
      return mapped.length > 0 ? mapped : null;
    }
    default:
      return null;
  }
}

/** 400601 时后端在 data.dataset_ids 返回越权的知识库，用于从已选项中剔除提示 */
export function outOfRangeIds(err: unknown): number[] {
  if (!(err instanceof ApiError) || err.code !== OpenErrorCode.DATASETS_OUT_OF_RANGE) return [];
  const ids = (err.data as { dataset_ids?: number[] } | null)?.dataset_ids;
  return Array.isArray(ids) ? ids : [];
}
