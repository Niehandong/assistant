import type {
  AssignableOrgNode,
  AssignPermission,
  AssignTargetType,
  AssignmentItem,
} from '@/services/types/kb-contract';

export const TARGET_TYPE_LABEL: Record<AssignTargetType, string> = {
  user: '个人',
  dept: '部门',
  company: '公司',
};
export const PERMISSION_LEVEL_LABEL: Record<AssignPermission, string> = {
  read: '只读',
  edit: '可编辑',
};

/** 添加弹窗的“含下级”默认值：部门默认是，公司默认否（个人忽略） */
export function defaultIncludeChildren(type: AssignTargetType): boolean {
  return type === 'dept';
}

export function includeChildrenLabel(type: AssignTargetType): string {
  return type === 'dept' ? '包含下级部门' : '包含下属公司';
}

export interface OrgTreeOption {
  value: number;
  title: string;
  disabled: boolean;
  children?: OrgTreeOption[];
}

/**
 * 组织树 -> TreeSelect 数据：类型为部门时只可选 dept 节点；
 * 类型为公司时只可选 company / group 节点。不符合类型的节点保留（用于展开层级）但置灰。
 */
export function toOrgTreeData(
  nodes: AssignableOrgNode[],
  type: Exclude<AssignTargetType, 'user'>,
): OrgTreeOption[] {
  return nodes.map((n) => {
    const selectable = type === 'dept' ? n.org_type === 'dept' : n.org_type !== 'dept';
    return {
      value: n.id,
      title: n.name,
      disabled: !selectable || n.status === 'disabled',
      children: n.children?.length ? toOrgTreeData(n.children, type) : undefined,
    };
  });
}

/** 展示：对象名称 + 路径；含下级标记 */
export function targetDescription(a: AssignmentItem): string {
  if (a.target_type === 'user') return a.target_name;
  return a.include_children
    ? `${a.target_name}（${includeChildrenLabel(a.target_type)}）`
    : a.target_name;
}

/** 管理操作（添加/修改/移除）：仅所有者且有分配权限码；可编辑用户只读查看 */
export function canManageAssignments(
  myPermission: 'owner' | 'edit' | 'read',
  can: (code: string) => boolean,
): boolean {
  return myPermission === 'owner' && can('kb:dataset:assign');
}
