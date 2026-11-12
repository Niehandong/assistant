import type { MyPermission } from '@/services/types/kb-contract';

export interface NavItem {
  key: string;
  label: string;
  /** 相对 /kb/datasets/:id 的路径 */
  path: string;
}

/**
 * 详情页左侧导航：按 my_permission 与权限码显示（FE-11）。
 * - 文档：所有可访问者
 * - 召回测试：kb:retrieval:test
 * - 设置：kb:dataset:update 且非只读（只读用户不显示设置导航）
 * - 分配：kb:dataset:list 且非只读（所有者可改，可编辑用户只读查看）
 */
export function buildNavItems(
  myPermission: MyPermission,
  can: (code: string) => boolean,
): NavItem[] {
  const items: NavItem[] = [{ key: 'documents', label: '文档', path: 'documents' }];
  if (can('kb:retrieval:test')) items.push({ key: 'recall', label: '召回测试', path: 'recall' });
  if (myPermission !== 'read') {
    if (can('kb:dataset:update')) items.push({ key: 'settings', label: '设置', path: 'settings' });
    if (can('kb:dataset:list')) {
      items.push({ key: 'assignments', label: '分配', path: 'assignments' });
    }
  }
  return items;
}

/** 当前路径对应的导航 key（上传、分段子页归属“文档”） */
export function activeNavKey(pathname: string, datasetId: number): string {
  const rest = pathname.replace(new RegExp(`^/kb/datasets/${datasetId}/?`), '');
  const first = rest.split('/')[0];
  return first || 'documents';
}
