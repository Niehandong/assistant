import { ApiError, ErrorCode, getErrorMessage } from '@/utils/error';

/** 登录失败文案：401102 优先用 data.remaining_seconds 换算分钟，缺失时回退后端 message */
export function getLoginErrorMessage(err: unknown): string {
  if (err instanceof ApiError && err.code === ErrorCode.LOGIN_LOCKED) {
    const seconds = (err.data as { remaining_seconds?: unknown } | null)?.remaining_seconds;
    if (typeof seconds === 'number' && seconds > 0) {
      return `账号已锁定，请 ${Math.ceil(seconds / 60)} 分钟后再试`;
    }
  }
  return getErrorMessage(err, '登录失败，请稍后重试');
}
