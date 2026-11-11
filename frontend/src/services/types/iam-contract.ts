/**
 * iam 认证接口类型（按 tech-design-m1.md 第 5.1 节契约手写）。
 * 后端 OpenAPI 就绪后，可由 `pnpm gen:api` 生成的 iam.d.ts 替换。
 */

export interface TokenResult {
  access_token: string;
  refresh_token: string;
  token_type: 'Bearer';
  expires_in: number;
  must_change_password: boolean;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface ChangePasswordRequest {
  old_password: string;
  new_password: string;
}

export interface CurrentUser {
  id: number;
  username: string;
  name: string;
  org_id: number;
  org_name: string | null;
  company_id: number | null;
  company_name: string | null;
  mobile: string | null;
  email: string | null;
  must_change_password: boolean;
  is_super_admin: boolean;
  last_login_at: string | null;
}

export interface MenuNode {
  code: string;
  name: string;
  /** 后端 OpenAPI 为可空（目录节点可能无 path） */
  path: string | null;
  icon: string | null;
  sort_order: number;
  children?: MenuNode[];
}

export interface MeResult {
  user: CurrentUser;
  permissions: string[];
  menus: MenuNode[];
}

/** 统一响应壳 */
export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

export interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ---------- 5.2 组织 ----------
export type OrgType = 'group' | 'company' | 'dept';
export type EnableStatus = 'enabled' | 'disabled';

export interface OrgNode {
  id: number;
  parent_id: number;
  name: string;
  code: string;
  org_type: OrgType;
  leader_user_id: number | null;
  leader_name: string | null;
  sort_order: number;
  status: EnableStatus;
  effective_status: EnableStatus;
  company_id: number | null;
  version: number;
  created_at: string;
  /** 是否在管理范围内（5.2.0a）；false 时只读，缺省视为 true */
  manageable?: boolean;
  /** 仅组织管理树（5.2.1）返回：非 null 时“停用”不可用，值为提示文案（403102/403103/400114） */
  disable_blocked_reason?: string | null;
  /** 仅组织管理树（5.2.1）返回：非 null 时“删除”不可用，值为提示文案（403102/400114） */
  delete_blocked_reason?: string | null;
  children: OrgNode[];
}

export interface OrgOption {
  id: number;
  parent_id: number;
  name: string;
  org_type: OrgType;
  status: EnableStatus;
  /** 是否在管理范围内（5.2.0a）；false 时不可作为写入目标，缺省视为 true */
  manageable?: boolean;
  children: OrgOption[];
}

export interface OrgCreateRequest {
  parent_id: number;
  org_type: Exclude<OrgType, 'group'>;
  name: string;
  code: string;
  leader_user_id?: number | null;
  sort_order?: number;
  status?: EnableStatus;
}

export interface OrgUpdateRequest {
  name: string;
  leader_user_id: number | null;
  sort_order: number;
  version: number;
}

// ---------- 5.3 用户 ----------
export interface RoleRef {
  id: number;
  name: string;
}

export interface UserItem {
  id: number;
  username: string;
  name: string;
  org_id: number;
  org_name: string | null;
  company_id: number | null;
  company_name: string | null;
  roles?: RoleRef[];
  mobile: string | null;
  email: string | null;
  status: EnableStatus;
  is_builtin: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
  created_at: string;
  version: number;
  /** 是否在管理范围内（5.2.0a）；false 时只读，缺省视为 true */
  manageable?: boolean;
}

export interface UserListQuery {
  page?: number;
  page_size?: number;
  org_id?: number;
  username?: string;
  name?: string;
  mobile?: string;
  status?: EnableStatus;
}

export interface UserCreateRequest {
  username: string;
  name: string;
  org_id: number;
  mobile?: string | null;
  email?: string | null;
  password?: string;
  role_ids?: number[];
  status?: EnableStatus;
}

export interface UserCreateResult {
  user: UserItem;
  initial_password: string | null;
}

export interface UserUpdateRequest {
  name: string;
  org_id: number;
  mobile: string | null;
  email: string | null;
  version: number;
}

export interface UserImpact {
  owned_dataset_count: number | null;
  api_key_count: number | null;
  degraded: boolean;
}

export interface AssignRolesRequest {
  role_ids: number[];
  confirm_self_lockout?: boolean;
}

// ---------- 5.4 角色 ----------
export type DataScope =
  'SELF' | 'DEPT' | 'DEPT_AND_CHILD' | 'COMPANY' | 'COMPANY_AND_CHILD' | 'ALL' | 'CUSTOM';

export type RoleType = 'group' | 'company';

export interface RoleItem {
  id: number;
  code: string;
  name: string;
  role_type: RoleType;
  owner_company_id: number | null;
  owner_company_name: string | null;
  data_scope: DataScope;
  status: EnableStatus;
  remark: string | null;
  is_builtin: boolean;
  builtin_key: string | null;
  user_count: number;
  editable: boolean;
  created_at: string;
  version: number;
}

export interface RoleDetail extends RoleItem {
  permission_ids: number[];
  custom_org_ids: number[];
}

export interface RoleListQuery {
  page?: number;
  page_size?: number;
  name?: string;
  code?: string;
  role_type?: RoleType;
  status?: EnableStatus;
  owner_company_id?: number;
}

export interface RoleCreateRequest {
  code: string;
  name: string;
  role_type: RoleType;
  owner_company_id?: number | null;
  data_scope?: DataScope;
  custom_org_ids?: number[];
  status?: EnableStatus;
  remark?: string | null;
}

export interface RoleUpdateRequest {
  name: string;
  status: EnableStatus;
  remark: string | null;
  version: number;
  confirm_self_lockout?: boolean;
}

export interface RoleGrantRequest {
  permission_ids: number[];
  data_scope: DataScope;
  custom_org_ids: number[];
  version: number;
  confirm_self_lockout?: boolean;
}

export interface AssignableRole {
  id: number;
  name: string;
  code: string;
  role_type: RoleType;
  data_scope: DataScope;
  assigned: boolean;
}

export interface PermissionNode {
  id: number;
  code: string;
  name: string;
  perm_type: 'menu' | 'button' | 'api';
  grantable: boolean;
  children: PermissionNode[];
}

export interface PermissionTreeResult {
  tree: PermissionNode[];
  max_data_scope: DataScope;
  can_custom: boolean;
}

// ---------- 5.5 日志 ----------
export interface LogQueryBase {
  page?: number;
  page_size?: number;
  start_time: string;
  end_time: string;
}

export interface OperationLogQuery extends LogQueryBase {
  operator?: string;
  module?: string;
  action?: string;
  result?: 'success' | 'failure';
}

export interface OperationLogItem {
  id: number;
  occurred_at: string;
  operator_id: number | null;
  operator_username: string | null;
  operator_name: string | null;
  company_name: string | null;
  module: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  target_name: string | null;
  result: 'success' | 'failure';
  error_message: string | null;
  ip: string | null;
  service: string;
}

export interface OperationLogDetail extends OperationLogItem {
  summary: unknown;
  user_agent: string | null;
  request_id: string | null;
}

export interface LoginLogQuery extends LogQueryBase {
  username?: string;
  result?: 'success' | 'failure';
  ip?: string;
}

export interface LoginLogItem {
  id: number;
  login_at: string;
  username: string;
  user_id: number | null;
  user_name: string | null;
  company_name: string | null;
  result: 'success' | 'failure';
  fail_reason: string | null;
  fail_message: string | null;
  ip: string | null;
  user_agent: string | null;
}
