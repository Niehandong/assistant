/** 统一业务错误对象：由响应拦截器抛出（tech-design 第 4.2 节错误码）。 */
export class ApiError extends Error {
  readonly code: number;
  readonly status: number;
  readonly data: unknown;

  constructor(code: number, message: string, data: unknown = null, status = 0) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.data = data;
  }
}

/** 网络异常 / 无法解析响应时使用的错误码 */
export const NETWORK_ERROR_CODE = -1;

export const ErrorCode = {
  PARAM_INVALID: 400001,
  UNAUTHORIZED: 401001,
  SESSION_INVALID: 401002,
  FORBIDDEN: 403001,
  MUST_CHANGE_PASSWORD: 403002,
  LOGIN_LOCKED: 401102,
  REFRESH_INVALID: 401104,
  VERSION_CONFLICT: 409001,
} as const;

export type ErrorAction = 'refresh' | 'login' | 'change-password' | 'toast';

/** 错误码分流：决定拦截器的处理动作 */
export function classifyError(code: number): ErrorAction {
  switch (code) {
    case ErrorCode.UNAUTHORIZED:
      return 'refresh';
    case ErrorCode.SESSION_INVALID:
    case ErrorCode.REFRESH_INVALID:
      return 'login';
    case ErrorCode.MUST_CHANGE_PASSWORD:
      return 'change-password';
    default:
      return 'toast';
  }
}

export function isApiError(err: unknown): err is ApiError {
  return err instanceof ApiError;
}

/** 提取 400001 的字段错误 */
export function getFieldErrors(err: unknown): { field: string; message: string }[] {
  if (!isApiError(err) || err.code !== ErrorCode.PARAM_INVALID) return [];
  const data = err.data as { errors?: { field: string; message: string }[] } | null;
  return data?.errors ?? [];
}

export function getErrorMessage(err: unknown, fallback = '操作失败，请稍后重试'): string {
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}
