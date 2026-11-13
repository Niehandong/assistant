import { http } from '@/api/request';
import type {
  AccessibleDataset,
  ApiKeyBody,
  ApiKeyItem,
  ApiKeyListQuery,
  ApiKeySecretResult,
  ApiKeyStatusBody,
  ApiKeyUpdateBody,
  AuditApiKeyItem,
  AuditApiKeyQuery,
  AuditCapabilities,
  AuditCallLogItem,
  AuditCallLogQuery,
  CallLogItem,
  CallLogQuery,
  PageResult,
  VersionBody,
} from './types/open-contract';

const OP = '/open-platform';

/** 5.1 我的 API 密钥（仅本人） */
export const apiKeyApi = {
  list: (params: ApiKeyListQuery) => http.get<PageResult<ApiKeyItem>>(`${OP}/api-keys`, { params }),
  detail: (id: number) => http.get<ApiKeyItem>(`${OP}/api-keys/${id}`),
  /** 响应含一次性明文，调用方不得缓存 */
  create: (body: ApiKeyBody) =>
    http.post<ApiKeySecretResult>(`${OP}/api-keys`, body, { skipErrorToast: true }),
  update: (id: number, body: ApiKeyUpdateBody) =>
    http.put<ApiKeyItem>(`${OP}/api-keys/${id}`, body, { skipErrorToast: true }),
  updateStatus: (id: number, body: ApiKeyStatusBody) =>
    http.put<ApiKeyItem>(`${OP}/api-keys/${id}/status`, body),
  /** 响应含一次性明文，调用方不得缓存 */
  regenerate: (id: number, body: VersionBody) =>
    http.post<ApiKeySecretResult>(`${OP}/api-keys/${id}/regenerate`, body),
  remove: (id: number) => http.delete<null>(`${OP}/api-keys/${id}`),
  accessibleDatasets: (id: number) =>
    http.get<AccessibleDataset[]>(`${OP}/api-keys/${id}/accessible-datasets`),
};

/** 5.2 我的调用日志 */
export const callLogApi = {
  list: (params: CallLogQuery) => http.get<PageResult<CallLogItem>>(`${OP}/call-logs`, { params }),
};

/** 5.3 API 密钥审计（管理员：只能停用、删除、查看） */
export const auditApi = {
  list: (params: AuditApiKeyQuery) =>
    http.get<PageResult<AuditApiKeyItem>>(`${OP}/audit/api-keys`, { params }),
  disable: (id: number, body: VersionBody) =>
    http.put<AuditApiKeyItem>(`${OP}/audit/api-keys/${id}/disable`, body),
  remove: (id: number) => http.delete<null>(`${OP}/audit/api-keys/${id}`),
  capabilities: () =>
    http.get<AuditCapabilities>(`${OP}/audit/capabilities`, { skipErrorToast: true }),
  callLogs: (params: AuditCallLogQuery) =>
    http.get<PageResult<AuditCallLogItem>>(`${OP}/audit/call-logs`, { params }),
};
