import type { AuditApiKeyItem, AuditStatus } from '@/services/types/open-contract';
import { STATUS_LABEL } from '../../openapi/keys/logic';

/** 审计页可筛选的 5 种状态（owner_unavailable 为近似筛选，展示值仍为精确计算） */
export const AUDIT_STATUS_OPTIONS = (
  ['enabled', 'disabled', 'admin_disabled', 'expired', 'owner_unavailable'] as AuditStatus[]
).map((k) => ({ label: STATUS_LABEL[k], value: k }));

export interface AuditRowActions {
  /** 停用：仅 admin_disabled 时隐藏；创建人自行停用（disabled）的也可锁定 */
  disable: boolean;
  remove: boolean;
  logs: boolean;
}

/** 管理员只能停用、删除、查看日志；不提供编辑 / 启用 / 重新生成（AC-72） */
export function auditRowActions(item: Pick<AuditApiKeyItem, 'stored_status'>): AuditRowActions {
  return { disable: item.stored_status !== 'admin_disabled', remove: true, logs: true };
}

export const CREATOR_STATUS_LABEL: Record<string, string> = {
  enabled: '启用',
  disabled: '已停用',
  deleted: '已删除',
};

/** 创建人状态非启用时的提示标签文案 */
export function creatorStatusTag(status: string): string | null {
  if (status === 'enabled') return null;
  return CREATOR_STATUS_LABEL[status] ?? status;
}

/** 审计列表不返回具体知识库 ID，只区分全部 / 指定 */
export function auditScopeText(item: Pick<AuditApiKeyItem, 'scope_type'>): string {
  return item.scope_type === 'all' ? '全部可访问' : '指定知识库';
}
