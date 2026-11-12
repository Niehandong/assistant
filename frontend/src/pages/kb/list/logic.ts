import type {
  ChunkMode,
  DatasetItem,
  DatasetListQuery,
  DatasetSortBy,
  MyPermission,
  SearchMethod,
} from '@/services/types/kb-contract';

export type ViewMode = 'card' | 'table';

export const VIEW_STORAGE_KEY = 'kb.dataset.viewMode';
export const PAGE_SIZE: Record<ViewMode, number> = { card: 24, table: 20 };

export const PERMISSION_LABEL: Record<MyPermission, string> = {
  owner: '所有者',
  edit: '可编辑',
  read: '只读',
};
export const CHUNK_MODE_LABEL: Record<ChunkMode, string> = {
  general: '通用分段',
  parent_child: '父子分段',
};
export const CHUNK_MODE_UNSET_TEXT = '首次上传时选择';
export const SEARCH_METHOD_LABEL: Record<SearchMethod, string> = {
  vector: '向量检索',
  full_text: '全文检索',
  hybrid: '混合检索',
};
export const SORT_OPTIONS: { value: DatasetSortBy; label: string }[] = [
  { value: 'updated_at', label: '最近更新' },
  { value: 'name', label: '名称' },
  { value: 'doc_count', label: '文档数' },
];

export function loadViewMode(storage: Pick<Storage, 'getItem'> = localStorage): ViewMode {
  try {
    return storage.getItem(VIEW_STORAGE_KEY) === 'table' ? 'table' : 'card';
  } catch {
    return 'card';
  }
}

export function saveViewMode(mode: ViewMode, storage: Pick<Storage, 'setItem'> = localStorage) {
  try {
    storage.setItem(VIEW_STORAGE_KEY, mode);
  } catch {
    // 偏好存储失败不影响使用
  }
}

export interface ListFilters {
  keyword?: string;
  my_permission?: MyPermission;
  owner_keyword?: string;
  chunk_mode?: ChunkMode | 'unset';
  only_owned?: boolean;
}

/** 构造列表请求参数：空串/未选条件不传；name 默认升序，其余降序 */
export function buildListQuery(
  filters: ListFilters,
  sortBy: DatasetSortBy,
  page: number,
  pageSize: number,
): DatasetListQuery {
  return {
    page,
    page_size: pageSize,
    keyword: filters.keyword?.trim() || undefined,
    my_permission: filters.my_permission || undefined,
    owner_keyword: filters.owner_keyword?.trim() || undefined,
    chunk_mode: filters.chunk_mode || undefined,
    only_owned: filters.only_owned ? true : undefined,
    sort_by: sortBy,
    sort_order: sortBy === 'name' ? 'asc' : 'desc',
  };
}

export function hasActiveFilter(filters: ListFilters): boolean {
  return Object.values(filters).some((v) => (typeof v === 'string' ? v.trim() !== '' : !!v));
}

export interface DatasetStats {
  /** 文档数 */
  docText: string;
  /** 处理中/失败徽标：为 0 不出现 */
  badges: { kind: 'processing' | 'failed'; text: string }[];
  /** 分段展示：父子为“父块 x / 子块 y”，其余为分段数 */
  segmentLabel: string;
  segmentText: string;
  chunkModeText: string;
  chunkModeUnset: boolean;
}

/** 卡片/列表统计展示规则（PRD F-08 规则 3、4，AC-25、AC-66） */
export function buildStats(d: DatasetItem): DatasetStats {
  const badges: DatasetStats['badges'] = [];
  if (d.processing_count > 0) {
    badges.push({ kind: 'processing', text: `处理中 ${d.processing_count}` });
  }
  if (d.failed_count > 0) {
    badges.push({ kind: 'failed', text: `失败 ${d.failed_count}` });
  }
  const parentChild = d.chunk_mode === 'parent_child';
  return {
    docText: String(d.doc_count),
    badges,
    segmentLabel: parentChild ? '分段' : '分段数',
    segmentText: parentChild
      ? `父块 ${d.segment_count} / 子块 ${d.child_segment_count}`
      : String(d.segment_count),
    chunkModeText: d.chunk_mode ? CHUNK_MODE_LABEL[d.chunk_mode] : CHUNK_MODE_UNSET_TEXT,
    chunkModeUnset: d.chunk_mode === null,
  };
}

export function ownerText(d: DatasetItem): string {
  switch (d.owner.status) {
    case 'disabled':
      return `${d.owner.name}（已停用）`;
    case 'deleted':
      return `${d.owner.name}（已删除）`;
    default:
      return d.owner.name;
  }
}

/** 向量模型已停用时的提示（PRD F-07 规则 7） */
export function modelDisabledHint(d: DatasetItem): string | null {
  return d.embedding_model.status === 'disabled' ? '向量模型已停用，请联系管理员' : null;
}

export interface DatasetActions {
  canSettings: boolean;
  canAssign: boolean;
  canDelete: boolean;
}

/** “...”菜单可用操作：权限码 + 我的权限级别（安全边界仍在后端） */
export function datasetActions(d: DatasetItem, can: (code: string) => boolean): DatasetActions {
  const isOwner = d.my_permission === 'owner';
  return {
    canSettings: can('kb:dataset:update') && d.my_permission !== 'read',
    canAssign: can('kb:dataset:assign') && isOwner,
    canDelete: can('kb:dataset:delete') && isOwner,
  };
}

/** 创建弹窗默认选中的 Embedding 模型：默认模型，否则不选 */
export function pickDefaultModelId(
  options: { id: number; is_default: boolean }[],
): number | undefined {
  return options.find((o) => o.is_default)?.id;
}
