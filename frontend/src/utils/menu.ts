import type { MenuNode } from '@/services/types/iam-contract';

/** 按 sort_order 升序（稳定） */
export function sortMenus(menus: MenuNode[]): SortedMenuNode[] {
  return [...menus]
    .sort((a, b) => a.sort_order - b.sort_order)
    .map((m) => ({ ...m, children: sortMenus(m.children ?? []) }));
}

export type SortedMenuNode = Omit<MenuNode, 'children'> & { children: SortedMenuNode[] };

/** 第一个可进入的叶子菜单路径（深度优先）；没有则返回 null */
export function findFirstMenuPath(menus: MenuNode[]): string | null {
  for (const m of sortMenus(menus)) {
    if (m.children.length > 0) {
      const p = findFirstMenuPath(m.children);
      if (p) return p;
    } else if (m.path) {
      return m.path;
    }
  }
  return null;
}

export interface LayoutRoute {
  path: string;
  name: string;
  icon: string | null;
  routes?: LayoutRoute[];
}

/** 后端菜单树 -> ProLayout route 数据 */
export function toLayoutRoutes(menus: MenuNode[]): LayoutRoute[] {
  return sortMenus(menus).map((m) => ({
    path: m.path ?? m.code,
    name: m.name,
    icon: m.icon,
    ...(m.children.length > 0 ? { routes: toLayoutRoutes(m.children) } : {}),
  }));
}
