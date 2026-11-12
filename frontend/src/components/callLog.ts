import dayjs, { type Dayjs } from 'dayjs';
import type { CallResult } from '@/services/types/open-contract';

export const LOG_MAX_RANGE_DAYS = 90;
export const LOG_DEFAULT_RANGE_DAYS = 7;
export const QUERY_PREVIEW_LEN = 50;

export const CALL_RESULT_LABEL: Record<CallResult, string> = {
  success: '成功',
  key_invalid: '密钥无效',
  key_disabled: '密钥已停用',
  key_expired: '密钥已过期',
  ip_not_allowed: 'IP 不在白名单',
  dataset_not_found: '知识库不存在或未授权',
  invalid_params: '参数不合法',
  rate_limited: '调用超限',
  model_unavailable: '模型服务不可用',
  service_unavailable: '服务不可用',
  internal_error: '内部错误',
};

export const CALL_RESULT_OPTIONS = (Object.keys(CALL_RESULT_LABEL) as CallResult[]).map((k) => ({
  label: CALL_RESULT_LABEL[k],
  value: k,
}));

export function callResultLabel(r: string): string {
  return CALL_RESULT_LABEL[r as CallResult] ?? r;
}

/** 成功绿色，限流/参数类黄色，其余红色 */
export function callResultColor(r: string): string {
  if (r === 'success') return 'success';
  if (r === 'rate_limited' || r === 'invalid_params' || r === 'dataset_not_found') return 'warning';
  return 'error';
}

/** 查询文本截断（超过 50 字加省略号，完整内容放悬停） */
export function truncateQuery(q: string | null | undefined, max = QUERY_PREVIEW_LEN): string {
  if (!q) return '-';
  const chars = Array.from(q);
  return chars.length > max ? `${chars.slice(0, max).join('')}…` : q;
}

/** 默认近 7 天 */
export function defaultLogRange(now: Dayjs = dayjs()): [Dayjs, Dayjs] {
  return [now.subtract(LOG_DEFAULT_RANGE_DAYS, 'day').startOf('day'), now.endOf('day')];
}

/** 时间范围校验：跨度不超过 90 天；通过返回 null */
export function validateLogRange(start?: Dayjs | null, end?: Dayjs | null): string | null {
  if (!start || !end) return '请选择时间范围';
  if (end.isBefore(start)) return '结束时间不能早于开始时间';
  if (end.diff(start, 'day', true) > LOG_MAX_RANGE_DAYS) {
    return `时间范围最长 ${LOG_MAX_RANGE_DAYS} 天`;
  }
  return null;
}

/** RangePicker disabledDate：不可选未来；已选起点后只允许 90 天内 */
export function isLogDateDisabled(
  current: Dayjs,
  from?: Dayjs | null,
  now: Dayjs = dayjs(),
): boolean {
  if (current.isAfter(now.endOf('day'))) return true;
  if (!from) return false;
  return Math.abs(current.startOf('day').diff(from.startOf('day'), 'day')) > LOG_MAX_RANGE_DAYS - 1;
}

export function parseLogRange(
  raw: unknown,
): { start: Dayjs; end: Dayjs; error: null } | { start: null; end: null; error: string } {
  const arr = Array.isArray(raw) ? (raw as unknown[]) : [];
  const start = arr[0] ? dayjs(arr[0] as string) : null;
  const end = arr[1] ? dayjs(arr[1] as string) : null;
  const error = validateLogRange(start, end);
  if (error || !start || !end) return { start: null, end: null, error: error ?? '请选择时间范围' };
  return { start, end, error: null };
}

/** 解析 URL 中的 api_key_id（非正整数忽略） */
export function parseApiKeyIdParam(raw: string | null | undefined): number | undefined {
  if (!raw || !/^\d+$/.test(raw)) return undefined;
  const n = Number(raw);
  return n > 0 ? n : undefined;
}
