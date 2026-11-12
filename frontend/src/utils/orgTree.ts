import type { OrgOption, OrgType } from '@/services/types/iam-contract';

interface TreeLike<T> {
  id: number;
  children?: T[];
}

export function findNode<T extends TreeLike<T>>(tree: T[], id: number): T | undefined {
  for (const n of tree) {
    if (n.id === id) return n;
    const hit = findNode(n.children ?? [], id);
    if (hit) return hit;
  }
  return undefined;
}

/** 节点自身及全部后代 id */
export function collectSubtreeIds<T extends TreeLike<T>>(node: T): number[] {
  return [node.id, ...(node.children ?? []).flatMap((c) => collectSubtreeIds(c))];
}

/** 所有节点 id（先序） */
export function collectAllIds<T extends TreeLike<T>>(tree: T[]): number[] {
  return tree.flatMap((n) => collectSubtreeIds(n));
}

/** 去掉空 children，避免表格显示无意义的展开图标 */
export function pruneEmptyChildren<T extends { children?: T[] }>(tree: T[]): T[] {
  return tree.map((n) => {
    const kids = pruneEmptyChildren(n.children ?? []);
    const { children: _omit, ...rest } = n;
    void _omit;
    return (kids.length > 0 ? { ...rest, children: kids } : rest) as T;
  });
}

/**
 * CUSTOM 数据范围「包含下级」：把选中的组织展开为自身 + 全部后代的具体 id（去重）。
 * 选中的 id 不在树中（范围外）时原样保留。
 */
export function expandWithDescendants(tree: OrgOption[], selected: number[]): number[] {
  const out = new Set<number>();
  for (const id of selected) {
    const node = findNode(tree, id);
    if (node) collectSubtreeIds(node).forEach((x) => out.add(x));
    else out.add(id);
  }
  return [...out];
}

/** 新增组织时，按上级类型限制可选类型：集团→公司/部门（集团本部可直接下设部门，TQ-07）；公司→公司/部门；部门→部门 */
export function allowedChildTypes(parentType: OrgType | undefined): Exclude<OrgType, 'group'>[] {
  switch (parentType) {
    case 'group':
      return ['company', 'dept'];
    case 'company':
      return ['company', 'dept'];
    case 'dept':
      return ['dept'];
    default:
      return [];
  }
}

/** 新上级类型是否允许承载该节点（用于移动） */
export function canBeChildOf(nodeType: OrgType, parentType: OrgType): boolean {
  if (nodeType === 'group') return false;
  return allowedChildTypes(parentType).includes(nodeType);
}

export const ORG_TYPE_LABEL: Record<OrgType, string> = {
  group: '集团',
  company: '公司',
  dept: '部门',
};

/**
 * 停用/删除/移动不可用的提示文案：直接使用 5.2.1 返回的 `*_blocked_reason`（null 表示可操作）；
 * 集团节点即使后端未给出文案也不可移动/停用/删除（400114）。已停用节点“启用”不受保护。
 */
export function getBlockedReason(
  node: {
    org_type: OrgType;
    status: 'enabled' | 'disabled';
    disable_blocked_reason?: string | null;
    delete_blocked_reason?: string | null;
    move_blocked_reason?: string | null;
  },
  action: 'disable' | 'delete' | 'move',
): string | null {
  const fallback = node.org_type === 'group' ? '集团节点不能移动、停用或删除' : null;
  if (action === 'disable') {
    if (node.status === 'disabled') return null;
    return node.disable_blocked_reason ?? fallback;
  }
  if (action === 'move') return node.move_blocked_reason ?? fallback;
  return node.delete_blocked_reason ?? fallback;
}

/** 是否在管理范围内（契约 5.2.0a）：缺省视为可管理，仅显式 false 为只读 */
export function isManageable(node: { manageable?: boolean }): boolean {
  return node.manageable !== false;
}
