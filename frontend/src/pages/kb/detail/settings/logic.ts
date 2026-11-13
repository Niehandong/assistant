import type { DatasetDetail } from '@/services/types/kb-contract';

/**
 * Embedding 模型可修改性：仅所有者且知识库内无文档时可改（403311 / 409312）。
 * 返回是否只读及提示文案。
 */
export function embeddingModelState(
  dataset: Pick<DatasetDetail, 'doc_count'>,
  isOwner: boolean,
): { readOnly: boolean; hint: string } {
  if (!isOwner) return { readOnly: true, hint: '只有所有者可以更换向量模型' };
  if (dataset.doc_count > 0) return { readOnly: true, hint: '已有文档，暂不支持更换向量模型' };
  return { readOnly: false, hint: '知识库内有文档后不能更换向量模型' };
}

/** 危险区（转移、删除）仅所有者可见，并需对应功能权限码 */
export function dangerZoneAccess(
  myPermission: DatasetDetail['my_permission'],
  can: (code: string) => boolean,
): { canTransfer: boolean; canDelete: boolean } {
  const owner = myPermission === 'owner';
  return {
    canTransfer: owner && can('kb:dataset:transfer'),
    canDelete: owner && can('kb:dataset:delete'),
  };
}

/** 设置页两个表单共享的版本守卫：保存始终使用 version，直到用户确认刷新才会采用最新版本 */
export interface VersionGuard {
  version: number;
  /** 本页自己保存成功后推进版本（两个表单共用同一条记录的 version） */
  onSaved: (newVersion: number) => void;
  /** 收到 409001：提示“已被他人修改”，不自动采用新 version */
  onConflict: () => void;
}

export const isVersionConflict = (err: unknown): boolean =>
  typeof err === 'object' && err !== null && (err as { code?: number }).code === 409001;
