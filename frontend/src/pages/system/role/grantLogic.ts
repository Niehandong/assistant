import type {
  DataScope,
  OrgOption,
  PermissionNode,
  PermissionTreeResult,
  RoleGrantRequest,
} from '@/services/types/iam-contract';
import { ApiError } from '@/utils/error';
import { expandWithDescendants } from '@/utils/orgTree';

/** 数据范围等级（契约 5.4.0）；CUSTOM 不参与等级比较 */
export const DATA_SCOPE_RANK: Record<Exclude<DataScope, 'CUSTOM'>, number> = {
  SELF: 1,
  DEPT: 2,
  DEPT_AND_CHILD: 3,
  COMPANY: 4,
  COMPANY_AND_CHILD: 5,
  ALL: 6,
};

export const DATA_SCOPE_LABEL: Record<DataScope, string> = {
  SELF: '仅本人',
  DEPT: '本部门',
  DEPT_AND_CHILD: '本部门及以下',
  COMPANY: '本公司',
  COMPANY_AND_CHILD: '本公司及下属公司',
  ALL: '全部数据',
  CUSTOM: '自定义组织',
};

export const DATA_SCOPE_ORDER: DataScope[] = [
  'SELF',
  'DEPT',
  'DEPT_AND_CHILD',
  'COMPANY',
  'COMPANY_AND_CHILD',
  'ALL',
  'CUSTOM',
];

/** 数据范围选项是否置灰：等级高于 max_data_scope；CUSTOM 取决于 can_custom */
export function isScopeDisabled(
  scope: DataScope,
  perm: Pick<PermissionTreeResult, 'max_data_scope' | 'can_custom'>,
): boolean {
  if (scope === 'CUSTOM') return !perm.can_custom;
  const max = perm.max_data_scope === 'CUSTOM' ? 0 : DATA_SCOPE_RANK[perm.max_data_scope];
  return DATA_SCOPE_RANK[scope] > max;
}

export interface PermTreeDatum {
  key: number;
  title: string;
  disableCheckbox: boolean;
  children?: PermTreeDatum[];
}

/** 权限树 -> antd Tree 数据；grantable=false 的节点置灰 */
export function toPermTreeData(tree: PermissionNode[]): PermTreeDatum[] {
  return tree.map((n) => ({
    key: n.id,
    title: n.perm_type === 'button' ? `${n.name}（按钮）` : n.name,
    disableCheckbox: !n.grantable,
    children: n.children?.length ? toPermTreeData(n.children) : undefined,
  }));
}

export function flattenPermissions(tree: PermissionNode[]): PermissionNode[] {
  return tree.flatMap((n) => [n, ...flattenPermissions(n.children ?? [])]);
}

/**
 * 提交的 permission_ids：只提交操作人可授予（grantable）的已勾选项。
 * 角色已有但操作人不拥有的权限，前端只置灰保留勾选，由后端合并保留（契约 5.4.0 授权上限）。
 */
export function buildGrantPermissionIds(checked: number[], tree: PermissionNode[]): number[] {
  const grantable = new Set(
    flattenPermissions(tree)
      .filter((n) => n.grantable)
      .map((n) => n.id),
  );
  return checked.filter((id) => grantable.has(id));
}

/** 403123 / 403124 等授权失败的友好提示 */
export function grantErrorMessage(err: unknown, tree: PermissionNode[]): string | null {
  if (!(err instanceof ApiError)) return null;
  if (err.code === 403123) {
    const codes = (err.data as { forbidden_codes?: string[] } | null)?.forbidden_codes ?? [];
    const names = new Map(flattenPermissions(tree).map((n) => [n.code, n.name]));
    const text = codes.map((c) => names.get(c) ?? c).join('、');
    return text ? `授予的权限超出您拥有的权限：${text}` : err.message;
  }
  if (err.code === 403124) return `数据范围超出您的数据范围：${err.message}`;
  return null;
}

export interface GrantFormState {
  checked: number[];
  dataScope: DataScope;
  customOrgIds: number[];
  includeChildren: boolean;
}

/** 组装授权请求体：权限只含可授予项；CUSTOM 时按「包含下级」展开具体组织 id，非 CUSTOM 不提交组织 */
export function buildGrantBody(
  state: GrantFormState,
  tree: PermissionNode[],
  orgOptions: OrgOption[],
  version: number,
): Omit<RoleGrantRequest, 'confirm_self_lockout'> {
  const custom = state.dataScope === 'CUSTOM';
  return {
    permission_ids: buildGrantPermissionIds(state.checked, tree),
    data_scope: state.dataScope,
    custom_org_ids: custom
      ? state.includeChildren
        ? expandWithDescendants(orgOptions, state.customOrgIds)
        : state.customOrgIds
      : [],
    version,
  };
}
