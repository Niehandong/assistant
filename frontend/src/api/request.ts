import { message } from 'antd';
import axios, {
  AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios';
import type { ApiResponse, TokenResult } from '@/services/types/iam-contract';
import { ApiError, NETWORK_ERROR_CODE, classifyError, type ErrorAction } from '@/utils/error';
import { redirectToChangePassword, redirectToLogin } from '@/utils/navigation';
import { tokenStore } from './tokenStore';

declare module 'axios' {
  interface AxiosRequestConfig {
    /** 为 true 时不自动弹出错误提示，由调用方处理 */
    skipErrorToast?: boolean;
    /** 内部标记：已重放过一次，避免循环刷新 */
    _retried?: boolean;
  }
}

const BASE_URL = '/api/v1';

/** 无拦截器的裸实例，仅用于刷新令牌 */
export const rawClient: AxiosInstance = axios.create({ baseURL: BASE_URL, timeout: 15000 });

export const client: AxiosInstance = axios.create({ baseURL: BASE_URL, timeout: 30000 });

/** 把任意响应体/异常规整为 ApiError */
function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  if (err instanceof AxiosError) {
    const body = err.response?.data as Partial<ApiResponse<unknown>> | undefined;
    if (body && typeof body.code === 'number') {
      return new ApiError(
        body.code,
        body.message ?? '请求失败',
        body.data ?? null,
        err.response?.status,
      );
    }
    if (err.response) {
      return new ApiError(err.response.status, '服务异常，请稍后重试', null, err.response.status);
    }
    return new ApiError(NETWORK_ERROR_CODE, '网络异常，请检查网络后重试');
  }
  return new ApiError(NETWORK_ERROR_CODE, err instanceof Error ? err.message : '未知错误');
}

// ---------- single-flight 刷新 ----------
let refreshing: Promise<string> | null = null;

/** 刷新令牌；并发调用共享同一个 Promise，保证同一时刻只发起一次刷新 */
export function refreshAccessToken(): Promise<string> {
  if (refreshing) return refreshing;
  const refreshToken = tokenStore.getRefresh();
  if (!refreshToken) {
    return Promise.reject(new ApiError(401104, '登录已过期，请重新登录'));
  }
  refreshing = rawClient
    .post<ApiResponse<TokenResult>>('/auth/refresh', { refresh_token: refreshToken })
    .then((res) => {
      const body = res.data;
      if (body.code !== 0) throw new ApiError(body.code, body.message, body.data);
      tokenStore.set(body.data.access_token, body.data.refresh_token);
      return body.data.access_token;
    })
    .catch((err: unknown) => {
      throw toApiError(err);
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

function goLogin(): void {
  tokenStore.clear();
  redirectToLogin();
}

async function handleError(
  err: ApiError,
  config: AxiosRequestConfig | undefined,
): Promise<AxiosResponse> {
  const action: ErrorAction = classifyError(err.code);
  if (action === 'refresh' && config && !config._retried) {
    try {
      const token = await refreshAccessToken();
      const retry: AxiosRequestConfig = {
        ...config,
        _retried: true,
        headers: { ...config.headers, Authorization: `Bearer ${token}` },
      };
      return await client.request(retry);
    } catch (refreshErr) {
      const e = toApiError(refreshErr);
      // 重放请求自身的业务错误（非认证类）原样抛出
      if (
        e.code !== 401001 &&
        e.code !== 401002 &&
        e.code !== 401104 &&
        e.code !== NETWORK_ERROR_CODE
      ) {
        throw e;
      }
      goLogin();
      throw e;
    }
  }
  if (action === 'refresh' || action === 'login') {
    goLogin();
  } else if (action === 'change-password') {
    redirectToChangePassword();
  } else if (!config?.skipErrorToast) {
    void message.error(err.message);
  }
  throw err;
}

client.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = tokenStore.getAccess();
  if (token && !config.headers.Authorization) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

client.interceptors.response.use(
  async (res) => {
    const body = res.data as ApiResponse<unknown> | undefined;
    if (body && typeof body.code === 'number' && body.code !== 0) {
      return handleError(new ApiError(body.code, body.message, body.data, res.status), res.config);
    }
    return res;
  },
  async (error: unknown) => {
    const config = error instanceof AxiosError ? error.config : undefined;
    const apiErr = toApiError(error);
    if (apiErr.code === NETWORK_ERROR_CODE && !config?.skipErrorToast) {
      void message.error(apiErr.message);
      throw apiErr;
    }
    return handleError(apiErr, config);
  },
);

async function unwrap<T>(p: Promise<{ data: ApiResponse<T> }>): Promise<T> {
  const res = await p;
  return res.data.data;
}

/** 业务请求入口：返回已解包的 data */
export const http = {
  get: <T>(url: string, config?: AxiosRequestConfig) =>
    unwrap<T>(client.get<ApiResponse<T>>(url, config)),
  post: <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
    unwrap<T>(client.post<ApiResponse<T>>(url, body, config)),
  put: <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
    unwrap<T>(client.put<ApiResponse<T>>(url, body, config)),
  patch: <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
    unwrap<T>(client.patch<ApiResponse<T>>(url, body, config)),
  delete: <T>(url: string, config?: AxiosRequestConfig) =>
    unwrap<T>(client.delete<ApiResponse<T>>(url, config)),
};
