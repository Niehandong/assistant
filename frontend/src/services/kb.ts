import { client, http } from '@/api/request';
import type {
  AssignableOrgNode,
  AssignableUser,
  AssignableUserQuery,
  AssignmentCreateRequest,
  AssignmentItem,
  AssignmentUpdateRequest,
  DatasetCreateRequest,
  DatasetDeleteRequest,
  DatasetDetail,
  DatasetItem,
  DatasetListQuery,
  DatasetOption,
  DatasetOptionQuery,
  DatasetTransferRequest,
  DatasetUpdateRequest,
  DocumentDetail,
  DocumentItem,
  DocumentListQuery,
  DocumentProgressItem,
  EnableStatus,
  ModelCreateRequest,
  ModelItem,
  ModelListQuery,
  ModelOption,
  ModelTestRequest,
  ModelTestResult,
  ModelType,
  ModelUpdateRequest,
  PageResult,
  PreviewResult,
  ProcessRule,
  RetrievalConfigUpdateRequest,
  SubmitDocumentsResult,
  UploadFileResult,
} from './types/kb-contract';
import type {
  AdminBatchTransferRequest,
  AdminDatasetDetail,
  AdminDatasetItem,
  AdminDatasetListQuery,
  AdminDetailQuery,
  AdminOwnerOption,
  AdminReceiver,
  AdminTransferRequest,
  ChildChunkItem,
  ChildChunkUpdateRequest,
  RetrievalResult,
  RetrieveHistoryItem,
  RetrieveTestRequest,
  SegmentCreateRequest,
  SegmentItem,
  SegmentListQuery,
  SegmentUpdateRequest,
} from './types/kb-contract';

const KB = '/kb';

/** 5.1 模型配置 */
export const modelApi = {
  list: (params: ModelListQuery) => http.get<PageResult<ModelItem>>(`${KB}/models`, { params }),
  create: (body: ModelCreateRequest) =>
    http.post<ModelItem>(`${KB}/models`, body, { skipErrorToast: true }),
  update: (id: number, body: ModelUpdateRequest) =>
    http.put<ModelItem>(`${KB}/models/${id}`, body, { skipErrorToast: true }),
  setStatus: (id: number, body: { status: EnableStatus; version: number }) =>
    http.put<ModelItem>(`${KB}/models/${id}/status`, body, { skipErrorToast: true }),
  setDefault: (id: number, body: { version: number }) =>
    http.put<ModelItem>(`${KB}/models/${id}/default`, body, { skipErrorToast: true }),
  remove: (id: number) => http.delete<null>(`${KB}/models/${id}`, { skipErrorToast: true }),
  /** 失败通过 success=false 返回，不抛 503 */
  test: (body: ModelTestRequest) =>
    http.post<ModelTestResult>(`${KB}/models/test`, body, { skipErrorToast: true, timeout: 60000 }),
  options: (model_type: ModelType) =>
    http.get<ModelOption[]>(`${KB}/models/options`, { params: { model_type } }),
};

/** 5.2 知识库 */
export const datasetApi = {
  list: (params: DatasetListQuery) =>
    http.get<PageResult<DatasetItem>>(`${KB}/datasets`, { params }),
  /** 5.2.2 可访问知识库选项（任一 kb:dataset:list / openapi:apikey:manage） */
  options: (params: DatasetOptionQuery) =>
    http.get<PageResult<DatasetOption>>(`${KB}/datasets/options`, { params }),
  detail: (id: number) => http.get<DatasetDetail>(`${KB}/datasets/${id}`),
  create: (body: DatasetCreateRequest) =>
    http.post<DatasetDetail>(`${KB}/datasets`, body, { skipErrorToast: true }),
  remove: (id: number, body: DatasetDeleteRequest) =>
    http.delete<null>(`${KB}/datasets/${id}`, { data: body, skipErrorToast: true }),
  update: (id: number, body: DatasetUpdateRequest) =>
    http.put<DatasetDetail>(`${KB}/datasets/${id}`, body, { skipErrorToast: true }),
  updateRetrievalConfig: (id: number, body: RetrievalConfigUpdateRequest) =>
    http.put<unknown>(`${KB}/datasets/${id}/retrieval-config`, body, { skipErrorToast: true }),
  transfer: (id: number, body: DatasetTransferRequest) =>
    http.post<DatasetDetail>(`${KB}/datasets/${id}/transfer`, body, { skipErrorToast: true }),
};

/** 5.3 分配 */
export const assignmentApi = {
  list: (datasetId: number) =>
    http.get<AssignmentItem[]>(`${KB}/datasets/${datasetId}/assignments`),
  create: (datasetId: number, body: AssignmentCreateRequest) =>
    http.post<AssignmentItem>(`${KB}/datasets/${datasetId}/assignments`, body, {
      skipErrorToast: true,
    }),
  update: (datasetId: number, id: number, body: AssignmentUpdateRequest) =>
    http.put<AssignmentItem>(`${KB}/datasets/${datasetId}/assignments/${id}`, body, {
      skipErrorToast: true,
    }),
  remove: (datasetId: number, id: number) =>
    http.delete<null>(`${KB}/datasets/${datasetId}/assignments/${id}`),
  assignableOrgs: (datasetId: number) =>
    http.get<AssignableOrgNode[]>(`${KB}/datasets/${datasetId}/assignable-orgs`),
  assignableUsers: (datasetId: number, params: AssignableUserQuery) =>
    http.get<PageResult<AssignableUser>>(`${KB}/datasets/${datasetId}/assignable-users`, {
      params,
    }),
};

/** 5.4 上传与预览 */
export const uploadApi = {
  /** 单文件上传（multipart）；失败由调用方逐文件展示，故关闭自动提示 */
  upload: (datasetId: number, file: File, onProgress?: (percent: number) => void) => {
    const form = new FormData();
    form.append('file', file);
    return http.post<UploadFileResult>(`${KB}/datasets/${datasetId}/upload-files`, form, {
      skipErrorToast: true,
      timeout: 120000,
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100));
      },
    });
  },
  preview: (datasetId: number, body: { upload_file_id: number; process_rule: ProcessRule }) =>
    http.post<PreviewResult>(`${KB}/datasets/${datasetId}/documents/preview`, body, {
      skipErrorToast: true,
      timeout: 90000,
    }),
  submit: (datasetId: number, body: { upload_file_ids: number[]; process_rule: ProcessRule }) =>
    http.post<SubmitDocumentsResult>(`${KB}/datasets/${datasetId}/documents`, body, {
      skipErrorToast: true,
    }),
};

/** 5.5 文档 */
export const documentApi = {
  list: (datasetId: number, params: DocumentListQuery) =>
    http.get<PageResult<DocumentItem>>(`${KB}/datasets/${datasetId}/documents`, { params }),
  progress: (datasetId: number, ids: number[]) =>
    http.get<DocumentProgressItem[]>(`${KB}/datasets/${datasetId}/documents/progress`, {
      params: { ids: ids.join(',') },
    }),
  detail: (datasetId: number, id: number) =>
    http.get<DocumentDetail>(`${KB}/datasets/${datasetId}/documents/${id}`),
  setEnabled: (datasetId: number, body: { document_ids: number[]; enabled: boolean }) =>
    http.put<{ updated: number }>(`${KB}/datasets/${datasetId}/documents/enabled`, body),
  batchDelete: (datasetId: number, body: { document_ids: number[] }) =>
    http.post<unknown>(`${KB}/datasets/${datasetId}/documents/batch-delete`, body),
  reprocess: (
    datasetId: number,
    id: number,
    body: { process_rule: ProcessRule; version: number },
  ) =>
    http.post<unknown>(`${KB}/datasets/${datasetId}/documents/${id}/reprocess`, body, {
      skipErrorToast: true,
    }),
  retry: (datasetId: number, id: number) =>
    http.post<unknown>(`${KB}/datasets/${datasetId}/documents/${id}/retry`),
  /** 原文件流式下载（非统一 JSON 响应）；出错时服务端返回统一 JSON，需自行解析 */
  download: async (
    datasetId: number,
    id: number,
  ): Promise<{ blob: Blob; filename: string | null }> => {
    // 错误时响应体为 Blob，由响应拦截器（parseBlobErrorBody）解析统一 JSON 的 message
    const res = await client.get<Blob>(`${KB}/datasets/${datasetId}/documents/${id}/download`, {
      responseType: 'blob',
      skipErrorToast: true,
    });
    return { blob: res.data, filename: parseFilename(res.headers['content-disposition']) };
  },
};

/** 解析 Content-Disposition 的 filename*=UTF-8''xxx（回退 filename=） */
export function parseFilename(header?: string | null): string | null {
  if (!header) return null;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch {
      return star[1].trim();
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1].trim() : null;
}

/** 5.6 分段（写操作均由页面处理 409511/409512/400511，关闭自动提示） */
export const segmentApi = {
  list: (datasetId: number, documentId: number, params: SegmentListQuery) =>
    http.get<PageResult<SegmentItem>>(
      `${KB}/datasets/${datasetId}/documents/${documentId}/segments`,
      { params },
    ),
  create: (datasetId: number, documentId: number, body: SegmentCreateRequest) =>
    http.post<SegmentItem>(`${KB}/datasets/${datasetId}/documents/${documentId}/segments`, body, {
      skipErrorToast: true,
    }),
  update: (datasetId: number, segmentId: number, body: SegmentUpdateRequest) =>
    http.put<SegmentItem>(`${KB}/datasets/${datasetId}/segments/${segmentId}`, body, {
      skipErrorToast: true,
    }),
  setEnabled: (datasetId: number, segmentId: number, enabled: boolean) =>
    http.put<unknown>(
      `${KB}/datasets/${datasetId}/segments/${segmentId}/enabled`,
      { enabled },
      { skipErrorToast: true },
    ),
  remove: (datasetId: number, segmentId: number) =>
    http.delete<null>(`${KB}/datasets/${datasetId}/segments/${segmentId}`, {
      skipErrorToast: true,
    }),
  createChild: (datasetId: number, segmentId: number, body: { content: string }) =>
    http.post<ChildChunkItem>(`${KB}/datasets/${datasetId}/segments/${segmentId}/children`, body, {
      skipErrorToast: true,
    }),
  updateChild: (datasetId: number, childId: number, body: ChildChunkUpdateRequest) =>
    http.put<ChildChunkItem>(`${KB}/datasets/${datasetId}/child-chunks/${childId}`, body, {
      skipErrorToast: true,
    }),
  removeChild: (datasetId: number, childId: number) =>
    http.delete<null>(`${KB}/datasets/${datasetId}/child-chunks/${childId}`, {
      skipErrorToast: true,
    }),
};

/** 5.7 召回测试（错误 409303/409506/503301 由页面展示，关闭自动提示；模型调用较慢，超时 60s） */
export const retrievalApi = {
  test: (datasetId: number, body: RetrieveTestRequest) =>
    http.post<RetrievalResult>(`${KB}/datasets/${datasetId}/retrieve-test`, body, {
      skipErrorToast: true,
      timeout: 60000,
    }),
  records: (datasetId: number) =>
    http.get<RetrieveHistoryItem[]>(`${KB}/datasets/${datasetId}/retrieve-records`),
};

/** 5.8 管理视图（只读审计 + 转移；无任何编辑/下载/召回测试接口） */
export const adminDatasetApi = {
  list: (params: AdminDatasetListQuery) =>
    http.get<PageResult<AdminDatasetItem>>(`${KB}/admin/datasets`, { params }),
  /** audit_entry=true 才记 admin_view 日志（5.8.1），仅用户主动进入时带 */
  detail: (id: number, params?: AdminDetailQuery) =>
    http.get<AdminDatasetDetail>(`${KB}/admin/datasets/${id}`, { params }),
  documents: (id: number, params: DocumentListQuery) =>
    http.get<PageResult<DocumentItem>>(`${KB}/admin/datasets/${id}/documents`, { params }),
  /** 文档详情（含 process_rule），不记日志 */
  documentDetail: (id: number, documentId: number) =>
    http.get<DocumentDetail>(`${KB}/admin/datasets/${id}/documents/${documentId}`),
  /** 仅 audit_entry=true 的主动进入请求记日志（5.8.1） */
  segments: (id: number, documentId: number, params: SegmentListQuery) =>
    http.get<PageResult<SegmentItem>>(
      `${KB}/admin/datasets/${id}/documents/${documentId}/segments`,
      { params },
    ),
  transfer: (id: number, body: AdminTransferRequest) =>
    http.post<unknown>(`${KB}/admin/datasets/${id}/transfer`, body, { skipErrorToast: true }),
  batchTransfer: (body: AdminBatchTransferRequest) =>
    http.post<{ transferred: number }>(`${KB}/admin/datasets/batch-transfer`, body, {
      skipErrorToast: true,
    }),
  receivers: (params: { keyword?: string; page?: number; page_size?: number }) =>
    http.get<PageResult<AdminReceiver>>(`${KB}/admin/receivers`, { params }),
  owners: (params: { keyword?: string }) =>
    http.get<AdminOwnerOption[]>(`${KB}/admin/owners`, { params }),
};
