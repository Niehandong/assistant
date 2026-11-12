import type {
  AdminDatasetItem,
  AdminDatasetListQuery,
  AdminBatchTransferRequest,
  AdminTransferRequest,
  OwnerStatus,
  TransferConflictData,
} from '@/services/types/kb-contract';
import { KbErrorCode } from '@/services/types/kb-contract';
import { isApiError } from '@/utils/error';

export const ADMIN_PAGE_SIZE = 20;
export const BATCH_DATASET_PAGE_SIZE = 100;

export const OWNER_STATUS_OPTIONS: { value: OwnerStatus; label: string }[] = [
  { value: 'enabled', label: '正常' },
  { value: 'disabled', label: '已停用' },
  { value: 'deleted', label: '已删除' },
];

export interface AdminFilters {
  keyword?: string;
  owner_keyword?: string;
  org_id?: number;
  owner_status?: OwnerStatus;
  pending_handover?: boolean;
}

/** 构造列表请求：空条件不传；“待交接”开关为 false 时不传 */
export function buildAdminQuery(
  f: AdminFilters,
  page: number,
  pageSize = ADMIN_PAGE_SIZE,
): AdminDatasetListQuery {
  return {
    page,
    page_size: pageSize,
    keyword: f.keyword?.trim() || undefined,
    owner_keyword: f.owner_keyword?.trim() || undefined,
    org_id: f.org_id || undefined,
    owner_status: f.owner_status || undefined,
    pending_handover: f.pending_handover ? true : undefined,
  };
}

/** 所有者停用或删除即“待交接” */
export const isPendingHandover = (status: OwnerStatus) => status !== 'enabled';

/** 所有者状态标签文案：正常不显示 */
export function ownerStatusTag(status: OwnerStatus): string | null {
  if (status === 'disabled') return '已停用';
  if (status === 'deleted') return '已删除';
  return null;
}

export function orgText(d: Pick<AdminDatasetItem, 'company' | 'dept'>): string {
  const c = d.company?.name;
  const p = d.dept?.name;
  if (c && p && c !== p) return `${c} / ${p}`;
  return p ?? c ?? '-';
}

/** 分段数：父子分段显示“父块 x / 子块 y” */
export function segmentText(
  d: Pick<AdminDatasetItem, 'chunk_mode' | 'segment_count' | 'child_segment_count'>,
): string {
  return d.chunk_mode === 'parent_child'
    ? `父块 ${d.segment_count} / 子块 ${d.child_segment_count}`
    : String(d.segment_count);
}

export function buildTransferBody(
  d: Pick<AdminDatasetItem, 'version'>,
  receiverId: number,
): AdminTransferRequest {
  return { receiver_user_id: receiverId, version: d.version };
}

/**
 * 批量转移请求：全选且已加载完整（total 不超过已加载数）时显式传 ID；
 * 全选但名下知识库未加载完时省略 dataset_ids（服务端 = 该用户名下范围内全部）。
 */
export function buildBatchBody(opts: {
  fromUserId: number;
  receiverId: number;
  selectedIds: number[];
  loadedCount: number;
  total: number;
}): AdminBatchTransferRequest {
  const body: AdminBatchTransferRequest = {
    from_user_id: opts.fromUserId,
    receiver_user_id: opts.receiverId,
  };
  const allSelected = opts.selectedIds.length === opts.loadedCount;
  if (!(allSelected && opts.total > opts.loadedCount)) body.dataset_ids = opts.selectedIds;
  return body;
}

/** 转移错误：409321 的 data.conflicts 为 [{dataset_id, dataset_name}] */
export function parseTransferError(err: unknown): { message: string; conflicts: string[] } {
  if (!isApiError(err)) {
    return { message: err instanceof Error ? err.message : '转移失败', conflicts: [] };
  }
  const conflicts =
    err.code === KbErrorCode.RECEIVER_NAME_CONFLICT
      ? ((err.data as TransferConflictData | null)?.conflicts ?? []).map((c) => c.dataset_name)
      : [];
  return { message: err.message, conflicts };
}
