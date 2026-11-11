import type { ReactNode } from 'react';
import PlaceholderPage from '@/pages/placeholder';
import LoginLogPage from '@/pages/system/log/login';
import OperationLogPage from '@/pages/system/log/operation';
import OrgPage from '@/pages/system/org';
import RolePage from '@/pages/system/role';
import UserPage from '@/pages/system/user';

/** 路由元信息：perm 为进入该路由所需权限码（满足任一即可） */
export interface RouteMeta {
  perm?: string | string[];
}

export interface AppRoute {
  path: string;
  element: ReactNode;
  meta?: RouteMeta;
}

const ph = (title: string) => <PlaceholderPage title={title} />;

/**
 * 主布局内的业务路由表（tech-design-m1.md 第 6 节映射）。
 * M1 页面（FE-05~08）与 M2/M3 页面先用占位组件，后续任务替换 element。
 * `/`、`/profile`、`/403`、`/404` 只需登录，在 AppRoutes 中单独声明。
 */
export const businessRoutes: AppRoute[] = [
  // M1
  { path: '/system/orgs', element: <OrgPage />, meta: { perm: 'system:org:list' } },
  { path: '/system/users', element: <UserPage />, meta: { perm: 'system:user:list' } },
  { path: '/system/roles', element: <RolePage />, meta: { perm: 'system:role:list' } },
  {
    path: '/system/logs/operation',
    element: <OperationLogPage />,
    meta: { perm: 'system:oplog:list' },
  },
  {
    path: '/system/logs/login',
    element: <LoginLogPage />,
    meta: { perm: 'system:loginlog:list' },
  },
  // M2
  { path: '/system/models', element: ph('模型配置'), meta: { perm: 'system:model:list' } },
  { path: '/kb/datasets/*', element: ph('知识库'), meta: { perm: 'kb:dataset:list' } },
  { path: '/system/datasets', element: ph('知识库管理'), meta: { perm: 'kb:admin:list' } },
  {
    path: '/system/datasets/:id',
    element: ph('知识库管理详情'),
    meta: { perm: 'kb:admin:view' },
  },
  // M3
  {
    path: '/openapi/keys',
    element: ph('我的 API 密钥'),
    meta: { perm: 'openapi:apikey:manage' },
  },
  { path: '/openapi/logs', element: ph('调用日志'), meta: { perm: 'openapi:log:list' } },
  { path: '/openapi/docs', element: ph('API 文档'), meta: { perm: 'openapi:doc:view' } },
  {
    path: '/system/api-keys',
    element: ph('API 密钥审计'),
    meta: { perm: 'openapi:apikey:audit' },
  },
];
