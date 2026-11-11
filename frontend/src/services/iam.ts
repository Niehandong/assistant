import { http, rawClient } from '@/api/request';
import type {
  ApiResponse,
  AssignableRole,
  AssignRolesRequest,
  ChangePasswordRequest,
  EnableStatus,
  LoginLogItem,
  LoginLogQuery,
  LoginRequest,
  MeResult,
  OperationLogDetail,
  OperationLogItem,
  OperationLogQuery,
  OrgCreateRequest,
  OrgNode,
  OrgOption,
  OrgUpdateRequest,
  PageResult,
  PermissionTreeResult,
  RoleCreateRequest,
  RoleDetail,
  RoleGrantRequest,
  RoleItem,
  RoleListQuery,
  RoleUpdateRequest,
  TokenResult,
  UserCreateRequest,
  UserCreateResult,
  UserImpact,
  UserItem,
  UserListQuery,
  UserUpdateRequest,
} from './types/iam-contract';

export const authApi = {
  /** 5.1.1 登录（public；错误由登录页自行处理，故关闭自动提示） */
  login: (body: LoginRequest) =>
    http.post<TokenResult>('/auth/login', body, { skipErrorToast: true }),
  /** 5.1.3 登出 */
  logout: () => http.post<null>('/auth/logout'),
  /** 5.1.4 当前用户、权限码、菜单（允许改密前调用） */
  me: () => http.get<MeResult>('/auth/me'),
  /** 5.1.5 修改本人密码 */
  changePassword: (body: ChangePasswordRequest) =>
    http.put<null>('/auth/password', body, { skipErrorToast: true }),
};

/** 5.1.2 刷新令牌：public，不带 access_token，不走 401 拦截（供非拦截场景直接调用） */
export async function refreshTokenRaw(refreshToken: string): Promise<TokenResult> {
  const res = await rawClient.post<ApiResponse<TokenResult>>('/auth/refresh', {
    refresh_token: refreshToken,
  });
  return res.data.data;
}

const SYS = '/system';

/** 5.2 组织 */
export const orgApi = {
  tree: (params?: { name?: string; status?: EnableStatus }) =>
    http.get<OrgNode[]>(`${SYS}/orgs/tree`, { params }),
  options: (params?: { types?: string; include_disabled?: boolean }) =>
    http.get<OrgOption[]>(`${SYS}/orgs/options`, { params }),
  create: (body: OrgCreateRequest) =>
    http.post<OrgNode>(`${SYS}/orgs`, body, { skipErrorToast: true }),
  update: (id: number, body: OrgUpdateRequest) =>
    http.put<OrgNode>(`${SYS}/orgs/${id}`, body, { skipErrorToast: true }),
  move: (id: number, body: { parent_id: number; version: number }) =>
    http.put<OrgNode>(`${SYS}/orgs/${id}/move`, body, { skipErrorToast: true }),
  setStatus: (id: number, body: { status: EnableStatus; version: number }) =>
    http.put<OrgNode>(`${SYS}/orgs/${id}/status`, body),
  remove: (id: number) => http.delete<null>(`${SYS}/orgs/${id}`, { skipErrorToast: true }),
};

/** 5.3 用户 */
export const userApi = {
  list: (params: UserListQuery) => http.get<PageResult<UserItem>>(`${SYS}/users`, { params }),
  create: (body: UserCreateRequest) =>
    http.post<UserCreateResult>(`${SYS}/users`, body, { skipErrorToast: true }),
  update: (id: number, body: UserUpdateRequest) =>
    http.put<UserItem>(`${SYS}/users/${id}`, body, { skipErrorToast: true }),
  setStatus: (id: number, body: { status: EnableStatus; version: number }) =>
    http.put<UserItem>(`${SYS}/users/${id}/status`, body),
  resetPassword: (id: number, body: { password?: string }) =>
    http.post<{ password: string | null }>(`${SYS}/users/${id}/reset-password`, body, {
      skipErrorToast: true,
    }),
  assignRoles: (id: number, body: AssignRolesRequest) =>
    http.put<null>(`${SYS}/users/${id}/roles`, body, { skipErrorToast: true }),
  remove: (id: number) => http.delete<null>(`${SYS}/users/${id}`),
  impact: (id: number) => http.get<UserImpact>(`${SYS}/users/${id}/impact`),
};

/** 5.4 角色与权限 */
export const roleApi = {
  list: (params: RoleListQuery) => http.get<PageResult<RoleItem>>(`${SYS}/roles`, { params }),
  /** user_id（分配角色）与 org_id（新建用户）二选一 */
  assignable: (target: { user_id: number } | { org_id: number }) =>
    http.get<AssignableRole[]>(`${SYS}/roles/assignable`, { params: target }),
  detail: (id: number) => http.get<RoleDetail>(`${SYS}/roles/${id}`),
  create: (body: RoleCreateRequest) =>
    http.post<RoleItem>(`${SYS}/roles`, body, { skipErrorToast: true }),
  update: (id: number, body: RoleUpdateRequest) =>
    http.put<RoleItem>(`${SYS}/roles/${id}`, body, { skipErrorToast: true }),
  grant: (id: number, body: RoleGrantRequest) =>
    http.put<RoleItem>(`${SYS}/roles/${id}/grants`, body, { skipErrorToast: true }),
  remove: (id: number) => http.delete<null>(`${SYS}/roles/${id}`),
  users: (id: number, params: { page?: number; page_size?: number }) =>
    http.get<PageResult<UserItem>>(`${SYS}/roles/${id}/users`, { params }),
  permissionTree: () => http.get<PermissionTreeResult>(`${SYS}/permissions/tree`),
};

/** 5.5 日志 */
export const logApi = {
  operationList: (params: OperationLogQuery) =>
    http.get<PageResult<OperationLogItem>>(`${SYS}/operation-logs`, { params }),
  operationDetail: (id: number) => http.get<OperationLogDetail>(`${SYS}/operation-logs/${id}`),
  loginList: (params: LoginLogQuery) =>
    http.get<PageResult<LoginLogItem>>(`${SYS}/login-logs`, { params }),
};
