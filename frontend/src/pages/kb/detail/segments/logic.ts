import type {
  DocumentStatus,
  IndexStatus,
  MyPermission,
  ProcessRule,
  SegmentItem,
  SegmentListQuery,
  SegmentType,
  SegmentUpdateRequest,
} from '@/services/types/kb-contract';
import { KbSegmentErrorCode } from '@/services/types/kb-contract';
import { isApiError } from '@/utils/error';

export const SEGMENT_PAGE_SIZE = 20;
export const KEYWORD_MAX_COUNT = 10;
export const KEYWORD_MAX_LENGTH = 20;
export const SEGMENT_POLL_INTERVAL_MS = 3000;
export const REGENERATE_CONFIRM_TEXT = '将按设置重新生成子块，子块的人工修改会丢失';
export const CONFLICT_TEXT = '该分段已被他人修改，已刷新为最新内容';

export type SegmentDocInfo = {
  id: number;
  name: string;
  chunk_mode: 'general' | 'parent_child';
  char_count: number;
  segment_count: number;
  child_count: number;
  status: DocumentStatus;
  process_rule?: ProcessRule | null;
};

/** 分段编辑权限：管理视图/只读用户/无权限码/文档非可用状态均不可编辑 */
export function resolveEditAccess(opts: {
  readonly: boolean;
  myPermission: MyPermission;
  hasUpdatePerm: boolean;
  docStatus: DocumentStatus;
}): { canEdit: boolean; reason: string | null } {
  if (opts.readonly || opts.myPermission === 'read' || !opts.hasUpdatePerm) {
    return { canEdit: false, reason: null };
  }
  if (opts.docStatus !== 'available') {
    return { canEdit: false, reason: '文档处理中或处理失败，暂不能编辑分段' };
  }
  return { canEdit: true, reason: null };
}

/** 各类内容的 token 上限（来自文档 process_rule；缺失时返回 null，以后端校验为准） */
export function contentLimit(rule: ProcessRule | null | undefined, type: SegmentType | 'child') {
  if (!rule) return null;
  if (rule.mode === 'general') return type === 'general' ? rule.general.max_tokens : null;
  if (type === 'child') return rule.child.max_tokens;
  if (type === 'parent') return rule.parent.mode === 'full_doc' ? 10000 : rule.parent.max_tokens;
  return null;
}

export interface ContentCheck {
  error: string | null;
  /** 粗略提示：按字符数估算可能超限（token 与字符并不等价，最终以后端 400511 为准） */
  warning: string | null;
}

export function checkContent(content: string, limit: number | null): ContentCheck {
  const len = content.trim().length;
  if (len === 0) return { error: '内容不能为空', warning: null };
  if (limit !== null && len > limit) {
    return {
      error: null,
      warning: `字符数已超过 ${limit}，可能超出长度上限，保存时以服务端校验为准`,
    };
  }
  return { error: null, warning: null };
}

/** 关键词规整：去首尾空格、去空、去重（保持顺序） */
export function normalizeKeywords(raw: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const k of raw) {
    const t = k.trim();
    if (t && !seen.has(t)) {
      seen.add(t);
      out.push(t);
    }
  }
  return out;
}

export function validateKeywords(raw: string[]): string | null {
  const list = normalizeKeywords(raw);
  if (list.length > KEYWORD_MAX_COUNT) return `关键词最多 ${KEYWORD_MAX_COUNT} 个`;
  if (list.some((k) => k.length > KEYWORD_MAX_LENGTH)) {
    return `每个关键词不超过 ${KEYWORD_MAX_LENGTH} 字`;
  }
  return null;
}

/** 索引状态标签文案；已索引返回 null */
export function indexStatusLabel(status: IndexStatus): string | null {
  switch (status) {
    case 'updating':
      return '索引更新中';
    case 'failed':
      return '索引更新失败';
    case 'pending':
      return '等待索引';
    default:
      return null;
  }
}

const isBusy = (s: IndexStatus) => s === 'updating' || s === 'pending';

/** 存在索引中的分段/子块时需要轮询刷新 */
export function needsPolling(items: SegmentItem[]): boolean {
  return items.some(
    (s) => isBusy(s.index_status) || s.children.some((c) => isBusy(c.index_status)),
  );
}

export function buildSegmentQuery(
  filters: { keyword?: string; enabled?: 'true' | 'false' },
  page: number,
  pageSize = SEGMENT_PAGE_SIZE,
): SegmentListQuery {
  return {
    page,
    page_size: pageSize,
    keyword: filters.keyword?.trim() || undefined,
    enabled: filters.enabled === undefined ? undefined : filters.enabled === 'true',
  };
}

export function buildUpdateBody(
  seg: Pick<SegmentItem, 'segment_type' | 'version'>,
  form: { content: string; keywords: string[] },
): SegmentUpdateRequest {
  const body: SegmentUpdateRequest = { content: form.content.trim(), version: seg.version };
  if (seg.segment_type === 'general') body.keywords = normalizeKeywords(form.keywords);
  else body.confirm_regenerate_children = true;
  return body;
}

export type SaveErrorKind = 'conflict' | 'too_long' | 'keywords' | 'other';

/** 保存失败分类：409511 -> conflict（需刷新） */
export function classifySaveError(err: unknown): { kind: SaveErrorKind; message: string } {
  if (isApiError(err)) {
    if (err.code === KbSegmentErrorCode.SEGMENT_VERSION_CONFLICT) {
      return { kind: 'conflict', message: CONFLICT_TEXT };
    }
    if (err.code === KbSegmentErrorCode.SEGMENT_TOO_LONG) {
      return { kind: 'too_long', message: err.message || '分段内容长度超出范围' };
    }
    if (err.code === KbSegmentErrorCode.KEYWORDS_INVALID) {
      return { kind: 'keywords', message: err.message || '关键词不合法' };
    }
    return { kind: 'other', message: err.message };
  }
  return { kind: 'other', message: err instanceof Error ? err.message : '操作失败' };
}
