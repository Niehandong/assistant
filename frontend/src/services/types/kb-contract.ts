/**
 * kb 服务接口契约类型（按 tech-design-m2.md 第 5 节手写）。
 * 后端 OpenAPI 就绪后，以 `pnpm gen:api` 生成到 src/services/types/kb.d.ts 的类型为准，
 * 2026-11-12 已与生成类型逐字段核对（字段名、可空性、枚举、查询参数、路径、错误码），无需修正；
 * 本文件保留为更严格的业务类型（枚举字面量、请求体可选项），生成类型由后端默认值导致部分字段标为必填/可选，仅作对照。
 */
import type { ApiResponse, EnableStatus, PageResult } from './iam-contract';

export type { ApiResponse, EnableStatus, PageResult };

// ---------- 5.0 错误码 ----------
export const KbErrorCode = {
  MODEL_TEST_FAILED: 400301,
  MODEL_DIMENSION_REQUIRED: 400302,
  MODEL_NOT_ENABLED: 400303,
  MODEL_IN_USE_MODIFY: 409301,
  MODEL_IN_USE_DELETE: 409302,
  MODEL_NAME_EXISTS: 409304,
  DATASET_NAME_MISMATCH: 400311,
  DATASET_NAME_EXISTS: 409311,
  EMBEDDING_MODEL_DISABLED: 409303,
  FORBIDDEN_LEVEL: 403311,
  HAS_DOCUMENTS: 409312,
  RECEIVER_INVALID: 400321,
  RECEIVER_IS_OWNER: 400322,
  RECEIVER_NAME_CONFLICT: 409321,
  ASSIGN_TO_OWNER: 400401,
  ASSIGN_OUT_OF_RANGE: 400402,
  ASSIGN_EXISTS: 409401,
  UNSUPPORTED_FILE: 400501,
  FILE_TOO_LARGE: 400502,
  FILE_EMPTY: 400503,
  FILE_BROKEN: 400504,
  NO_TEXT: 400505,
  DOC_TOO_LONG: 400506,
  UPLOAD_EXPIRED: 400508,
  DUPLICATE_CONTENT: 409501,
  DOC_LIMIT: 409502,
  CHUNK_MODE_LOCKED: 409503,
  DOC_PROCESSING: 409504,
} as const;

// ---------- 5.1 模型配置 ----------
export type ModelType = 'embedding' | 'rerank';

export interface ModelItem {
  id: number;
  name: string;
  model_type: ModelType;
  base_url: string;
  model_name: string;
  api_key_hint: string | null;
  dimension: number | null;
  max_input_tokens: number;
  status: EnableStatus;
  is_default: boolean;
  dataset_count: number;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ModelListQuery {
  page?: number;
  page_size?: number;
  model_type?: ModelType;
  status?: EnableStatus;
  keyword?: string;
}

export interface ModelCreateRequest {
  name: string;
  model_type: ModelType;
  base_url: string;
  model_name: string;
  api_key?: string;
  dimension?: number | null;
  max_input_tokens?: number;
  status?: EnableStatus;
  is_default?: boolean;
}

/** api_key：不传/null = 不修改，"" = 清空 */
export interface ModelUpdateRequest {
  name: string;
  base_url: string;
  model_name: string;
  api_key?: string | null;
  dimension?: number | null;
  max_input_tokens?: number;
  status?: EnableStatus;
  is_default?: boolean;
  version: number;
}

export interface ModelTestRequest {
  model_id?: number;
  model_type: ModelType;
  base_url?: string;
  model_name?: string;
  api_key?: string;
}

export interface ModelTestResult {
  success: boolean;
  dimension: number | null;
  latency_ms: number | null;
  error_message: string | null;
}

export interface ModelOption {
  id: number;
  name: string;
  model_type: ModelType;
  dimension: number | null;
  max_input_tokens: number;
  is_default: boolean;
}

/** 409301 / 409302 的 data */
export interface ModelInUseData {
  datasets: string[];
  total: number;
}

// ---------- 5.2 知识库 ----------
export type MyPermission = 'owner' | 'edit' | 'read';
export type ChunkMode = 'general' | 'parent_child';
export type SearchMethod = 'vector' | 'full_text' | 'hybrid';
export type OwnerStatus = 'enabled' | 'disabled' | 'deleted';

export interface DatasetOwner {
  id: number;
  name: string;
  status: OwnerStatus;
}

export interface DatasetModelRef {
  id: number;
  name: string;
  status: EnableStatus;
}

export interface DatasetItem {
  id: number;
  name: string;
  description: string | null;
  icon: string | null;
  owner: DatasetOwner;
  my_permission: MyPermission;
  chunk_mode: ChunkMode | null;
  indexing_technique: string;
  search_method: SearchMethod;
  doc_count: number;
  processing_count: number;
  failed_count: number;
  available_doc_count: number;
  segment_count: number;
  child_segment_count: number;
  char_count: number;
  embedding_model: DatasetModelRef;
  created_at: string;
  updated_at: string;
}

export interface RetrievalConfig {
  search_method: SearchMethod;
  top_k: number;
  score_threshold_enabled: boolean;
  score_threshold: number;
  reranking_enable: boolean;
  reranking_model_id: number | null;
  hybrid_mode: 'weighted' | 'rerank';
  vector_weight: number;
}

export interface DatasetOwnerOrg {
  company_id: number;
  company_name: string;
  dept_id: number;
  dept_name: string;
}

export interface DatasetDetail extends DatasetItem {
  retrieval_config: RetrievalConfig;
  last_process_rule: Record<string, unknown> | null;
  owner_org: DatasetOwnerOrg;
  assignment_count: number;
  version: number;
}

export type DatasetSortBy = 'updated_at' | 'name' | 'doc_count';

export interface DatasetListQuery {
  page?: number;
  page_size?: number;
  keyword?: string;
  my_permission?: MyPermission;
  owner_keyword?: string;
  chunk_mode?: ChunkMode | 'unset';
  only_owned?: boolean;
  sort_by?: DatasetSortBy;
  sort_order?: 'asc' | 'desc';
}

export interface DatasetCreateRequest {
  name: string;
  description?: string | null;
  icon?: string | null;
  embedding_model_id?: number;
  retrieval_config?: RetrievalConfig;
}

export interface DatasetDeleteRequest {
  confirm_name: string;
}

// ---------- 5.2.5 / 5.2.6 / 5.2.8 知识库更新、检索设置、转移 ----------
export interface DatasetUpdateRequest {
  name: string;
  description?: string | null;
  icon?: string | null;
  /** 与当前不同时要求所有者且无文档（403311 / 409312） */
  embedding_model_id?: number;
  version: number;
}

export interface RetrievalConfigUpdateRequest {
  retrieval_config: RetrievalConfig;
  version: number;
}

export interface DatasetTransferRequest {
  receiver_user_id: number;
  version: number;
}

// ---------- 5.3 分配 ----------
export type AssignTargetType = 'user' | 'dept' | 'company';
export type AssignPermission = 'read' | 'edit';

export interface AssignmentItem {
  id: number;
  target_type: AssignTargetType;
  target_id: number;
  target_name: string;
  target_path: string | null;
  /** false：对象已删除，分配自动失效，仅展示 */
  target_valid: boolean;
  include_children: boolean;
  permission: AssignPermission;
  created_by: { id: number; name: string };
  created_at: string;
}

export interface AssignmentCreateRequest {
  target_type: AssignTargetType;
  target_id: number;
  include_children?: boolean;
  permission?: AssignPermission;
}

export interface AssignmentUpdateRequest {
  permission: AssignPermission;
  include_children: boolean;
}

export type AssignableOrgType = 'group' | 'company' | 'dept';

export interface AssignableOrgNode {
  id: number;
  parent_id: number;
  name: string;
  org_type: AssignableOrgType;
  status: EnableStatus;
  children: AssignableOrgNode[];
}

export interface AssignableUser {
  id: number;
  username: string;
  name: string;
  org_name: string | null;
  company_name: string | null;
}

export interface AssignableUserQuery {
  keyword?: string;
  org_id?: number;
  page?: number;
  page_size?: number;
}

// ---------- 3.5 分段规则 ----------
export interface PreProcessing {
  normalize_whitespace: boolean;
  remove_urls_emails: boolean;
}

export interface GeneralProcessRule {
  mode: 'general';
  pre_processing: PreProcessing;
  general: { separator: string; max_tokens: number; chunk_overlap: number };
}

export interface ParentChildProcessRule {
  mode: 'parent_child';
  pre_processing: PreProcessing;
  parent: { mode: 'paragraph' | 'full_doc'; separator: string; max_tokens: number };
  child: { separator: string; max_tokens: number };
}

export type ProcessRule = GeneralProcessRule | ParentChildProcessRule;

// ---------- 5.4 上传与预览 ----------
export interface UploadFileResult {
  upload_file_id: number;
  name: string;
  file_ext: string;
  file_size: number;
  file_hash: string;
}

export interface PreviewChild {
  position: number;
  content: string;
  char_count: number;
  token_count: number;
}

export interface PreviewSegment extends PreviewChild {
  children: PreviewChild[];
}

export interface PreviewResult {
  mode: ChunkMode;
  total_segments: number;
  total_child_chunks: number;
  doc_token_count: number;
  segments: PreviewSegment[];
}

export interface DuplicateFile {
  upload_file_id: number;
  existing_document_name: string;
}

export interface SubmitDocumentsResult {
  documents: { id: number; name: string; status: DocumentStatus }[];
}

// ---------- 5.5 文档 ----------
export type DocumentStatus =
  'queued' | 'parsing' | 'splitting' | 'indexing' | 'available' | 'failed';

export interface DocumentProgressInfo {
  done: number;
  total: number;
}

export interface DocumentItem {
  id: number;
  name: string;
  file_ext: string;
  file_size: number;
  chunk_mode: ChunkMode;
  char_count: number;
  segment_count: number;
  child_count: number;
  hit_count: number;
  uploaded_by: { id: number; name: string };
  created_at: string;
  status: DocumentStatus;
  progress: DocumentProgressInfo | null;
  error_code: string | null;
  error_message: string | null;
  enabled: boolean;
  version: number;
}

export interface DocumentDetail extends DocumentItem {
  process_rule: ProcessRule | null;
}

/** query status 另支持 processing（= queued/parsing/splitting/indexing） */
export type DocumentStatusFilter = DocumentStatus | 'processing';

export interface DocumentListQuery {
  page?: number;
  page_size?: number;
  keyword?: string;
  status?: DocumentStatusFilter;
  enabled?: boolean;
  sort_by?: 'created_at' | 'char_count' | 'hit_count';
  sort_order?: 'asc' | 'desc';
}

export interface DocumentProgressItem {
  id: number;
  status: DocumentStatus;
  progress: DocumentProgressInfo | null;
  error_code: string | null;
  error_message: string | null;
  segment_count: number;
  child_count: number;
  char_count: number;
}

// ---------- 5.0 错误码补充（分段/召回，FE-13/14） ----------
export const KbSegmentErrorCode = {
  SEGMENT_TOO_LONG: 400511,
  KEYWORDS_INVALID: 400512,
  OP_NOT_SUPPORTED: 400513,
  SEGMENT_VERSION_CONFLICT: 409511,
  CONFIRM_REGENERATE: 409512,
  NO_AVAILABLE_DOC: 409506,
  MODEL_CALL_FAILED: 503301,
} as const;

// ---------- 5.6 分段 ----------
export type SegmentType = 'general' | 'parent';
export type IndexStatus = 'pending' | 'indexed' | 'updating' | 'failed';

export interface ChildChunkItem {
  id: number;
  position: number;
  content: string;
  char_count: number;
  token_count: number;
  edited: boolean;
  index_status: IndexStatus;
  index_error: string | null;
  version: number;
}

export interface SegmentItem {
  id: number;
  position: number;
  segment_type: SegmentType;
  content: string;
  keywords: string[];
  char_count: number;
  token_count: number;
  enabled: boolean;
  edited: boolean;
  hit_count: number;
  index_status: IndexStatus;
  index_error: string | null;
  version: number;
  children: ChildChunkItem[];
}

export interface SegmentListQuery {
  /** 仅管理视图：用户主动进入时带 true（5.8.1），翻页/搜索/重取不带 */
  audit_entry?: boolean;
  page?: number;
  page_size?: number;
  keyword?: string;
  enabled?: boolean;
}

export interface SegmentCreateRequest {
  content: string;
  keywords?: string[];
}

export interface SegmentUpdateRequest {
  content: string;
  /** 仅通用分段 */
  keywords?: string[];
  version: number;
  /** 父块必须为 true，否则 409512 */
  confirm_regenerate_children?: boolean;
}

export interface ChildChunkUpdateRequest {
  content: string;
  version: number;
}

// ---------- 5.7 召回测试 ----------
export interface RecallRetrievalConfig extends RetrievalConfig {
  reranking_model_name?: string | null;
}

export interface RecallChildChunk {
  id: number;
  position: number;
  content: string;
  score: number;
}

export interface RecallRecord {
  segment_id: number;
  position: number;
  segment_type: SegmentType;
  content: string;
  score: number;
  keywords: string[];
  document: { id: number; name: string };
  child_chunks: RecallChildChunk[];
}

export interface RetrievalResult {
  query: string;
  retrieval_config: RecallRetrievalConfig;
  rerank_skipped: boolean;
  rerank_skipped_reason: string | null;
  records: RecallRecord[];
}

export interface RetrieveTestRequest {
  query: string;
  retrieval_config?: RetrievalConfig;
}

export interface RetrieveHistoryItem {
  id: number;
  query: string;
  search_method: SearchMethod;
  retrieval_config: RetrievalConfig;
  result_count: number;
  created_at: string;
}

// ---------- 5.8 管理视图 ----------
export interface AdminOwner {
  id: number;
  name: string;
  username: string;
  status: OwnerStatus;
}

export interface AdminDatasetItem {
  id: number;
  name: string;
  owner: AdminOwner;
  company: { id: number; name: string } | null;
  dept: { id: number; name: string } | null;
  chunk_mode: ChunkMode | null;
  doc_count: number;
  segment_count: number;
  child_segment_count: number;
  assignment_count: number;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface AdminDatasetDetail extends AdminDatasetItem {
  description: string | null;
  embedding_model: DatasetModelRef;
  retrieval_config: RetrievalConfig;
  assignments: AssignmentItem[];
}

export interface AdminDatasetListQuery {
  page?: number;
  page_size?: number;
  keyword?: string;
  owner_keyword?: string;
  owner_id?: number;
  org_id?: number;
  owner_status?: OwnerStatus;
  pending_handover?: boolean;
}

export interface AdminTransferRequest {
  receiver_user_id: number;
  version: number;
}

export interface AdminBatchTransferRequest {
  from_user_id: number;
  receiver_user_id: number;
  dataset_ids?: number[];
}

export interface AdminReceiver {
  id: number;
  username: string;
  name: string;
  org_name: string | null;
  company_name: string | null;
}

export interface AdminOwnerOption {
  id: number;
  username: string;
  name: string;
  status: OwnerStatus;
  dataset_count: number;
}

/** 409321 的 data（批量转移时的同名冲突） */
export interface TransferConflictData {
  conflicts?: { dataset_id: number; dataset_name: string }[];
}

export interface AdminDetailQuery {
  audit_entry?: boolean;
}

// ---------- 5.2.2 可访问知识库选项（API 密钥"指定知识库"、调用日志筛选） ----------
export interface DatasetOption {
  id: number;
  name: string;
  my_permission: 'owner' | 'edit' | 'read';
}

export interface DatasetOptionQuery {
  keyword?: string;
  page?: number;
  page_size?: number;
}
