import dayjs, { type Dayjs } from 'dayjs';

export const MAX_RANGE_DAYS = 180;
export const DEFAULT_RANGE_DAYS = 7;

/** 默认时间范围：近 7 天 */
export function defaultRange(now: Dayjs = dayjs()): [Dayjs, Dayjs] {
  return [now.subtract(DEFAULT_RANGE_DAYS, 'day').startOf('day'), now.endOf('day')];
}

/** 校验范围；通过返回 null，否则返回提示文案 */
export function validateRange(start?: Dayjs | null, end?: Dayjs | null): string | null {
  if (!start || !end) return '请选择时间范围';
  if (end.isBefore(start)) return '结束时间不能早于开始时间';
  if (end.diff(start, 'day', true) > MAX_RANGE_DAYS) return `时间范围最长 ${MAX_RANGE_DAYS} 天`;
  return null;
}

/**
 * RangePicker 的 disabledDate：已选择开始时间后（from），只允许 ±180 天内的日期；
 * 同时不允许选择未来日期。
 */
export function isDateDisabled(current: Dayjs, from?: Dayjs | null, now: Dayjs = dayjs()): boolean {
  if (current.isAfter(now.endOf('day'))) return true;
  if (!from) return false;
  return Math.abs(current.startOf('day').diff(from.startOf('day'), 'day')) > MAX_RANGE_DAYS - 1;
}

/** 转为带时区偏移的 ISO 8601（契约 4.1） */
export function toIso(d: Dayjs): string {
  return d.format();
}

/** 从 ProTable 表单值（字符串或 dayjs）解析时间范围 */
export function parseRangeParam(
  raw: unknown,
): { start: Dayjs; end: Dayjs; error: null } | { start: null; end: null; error: string } {
  const arr = Array.isArray(raw) ? (raw as unknown[]) : [];
  const start = arr[0] ? dayjs(arr[0] as string) : null;
  const end = arr[1] ? dayjs(arr[1] as string) : null;
  const error = validateRange(start, end);
  if (error || !start || !end) return { start: null, end: null, error: error ?? '请选择时间范围' };
  return { start, end, error: null };
}
