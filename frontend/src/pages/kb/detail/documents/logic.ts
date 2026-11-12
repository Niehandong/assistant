import type {
  DocumentItem,
  DocumentListQuery,
  DocumentProgressItem,
  DocumentStatus,
  DocumentStatusFilter,
} from '@/services/types/kb-contract';
import { formatNumber } from '@/utils/format';

export const STATUS_LABEL: Record<DocumentStatus, string> = {
  queued: '排队中',
  parsing: '解析中',
  splitting: '分段中',
  indexing: '索引中',
  available: '可用',
  failed: '失败',
};

export const STATUS_FILTER_OPTIONS: { value: DocumentStatusFilter; label: string }[] = [
  { value: 'processing', label: '处理中' },
  { value: 'available', label: '可用' },
  { value: 'failed', label: '失败' },
  { value: 'queued', label: '排队中' },
  { value: 'parsing', label: '解析中' },
  { value: 'splitting', label: '分段中' },
  { value: 'indexing', label: '索引中' },
];

export const POLL_INTERVAL_MS = 3000;
export const PROGRESS_BATCH = 50;

export function isTerminal(status: DocumentStatus): boolean {
  return status === 'available' || status === 'failed';
}

/** 非终态文档 ID（需要轮询），按接口上限 50 切批 */
export function pendingIds(rows: Pick<DocumentItem, 'id' | 'status'>[]): number[] {
  return rows.filter((r) => !isTerminal(r.status)).map((r) => r.id);
}

export function chunkIds(ids: number[], size = PROGRESS_BATCH): number[][] {
  const out: number[][] = [];
  for (let i = 0; i < ids.length; i += size) out.push(ids.slice(i, i + size));
  return out;
}

/** 把 progress 接口结果局部合并到列表行（未返回的行保持不变；不改变 enabled/version 等字段） */
export function mergeProgress(
  rows: DocumentItem[],
  progress: DocumentProgressItem[],
): DocumentItem[] {
  if (progress.length === 0) return rows;
  const map = new Map(progress.map((p) => [p.id, p]));
  return rows.map((r) => {
    const p = map.get(r.id);
    return p
      ? {
          ...r,
          status: p.status,
          progress: p.progress,
          error_code: p.error_code,
          error_message: p.error_message,
          segment_count: p.segment_count,
          child_count: p.child_count,
          char_count: p.char_count,
        }
      : r;
  });
}

/** 状态文案：索引中显示进度“索引中 60/120” */
export function statusText(r: Pick<DocumentItem, 'status' | 'progress'>): string {
  const base = STATUS_LABEL[r.status];
  if (r.status === 'indexing' && r.progress && r.progress.total > 0) {
    return `${base} ${r.progress.done}/${r.progress.total}`;
  }
  return base;
}

/** 分段数列：父子显示“父块/子块” */
export function segmentCountText(
  r: Pick<DocumentItem, 'chunk_mode' | 'segment_count' | 'child_count'>,
): string {
  return r.chunk_mode === 'parent_child'
    ? `${formatNumber(r.segment_count)} / ${formatNumber(r.child_count)}`
    : formatNumber(r.segment_count);
}

export interface DocFilters {
  keyword?: string;
  status?: DocumentStatusFilter;
  enabled?: 'true' | 'false';
}

export interface DocSort {
  sort_by: 'created_at' | 'char_count' | 'hit_count';
  sort_order: 'asc' | 'desc';
}

export const DEFAULT_DOC_SORT: DocSort = { sort_by: 'created_at', sort_order: 'desc' };

export function buildDocQuery(
  f: DocFilters,
  sort: DocSort,
  page: number,
  pageSize: number,
): DocumentListQuery {
  return {
    page,
    page_size: pageSize,
    keyword: f.keyword?.trim() || undefined,
    status: f.status || undefined,
    enabled: f.enabled === undefined ? undefined : f.enabled === 'true',
    ...sort,
  };
}

/** antd 表格 sorter -> 接口排序；取消排序回到默认 */
export function toDocSort(
  field: string | undefined,
  order: 'ascend' | 'descend' | null | undefined,
): DocSort {
  if (!order || (field !== 'created_at' && field !== 'char_count' && field !== 'hit_count')) {
    return DEFAULT_DOC_SORT;
  }
  return { sort_by: field, sort_order: order === 'ascend' ? 'asc' : 'desc' };
}

export const canReprocess = (r: Pick<DocumentItem, 'status'>) =>
  r.status === 'available' || r.status === 'failed';
export const canRetry = (r: Pick<DocumentItem, 'status'>) => r.status === 'failed';

/** 浏览器下载 Blob */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
