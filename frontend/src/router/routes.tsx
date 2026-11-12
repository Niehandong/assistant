import type { ReactNode } from 'react';
import DatasetDetailRoutes from '@/pages/kb/detail/routes';
import DatasetListPage from '@/pages/kb/list';
import ApiDocsPage from '@/pages/openapi/docs';
import ApiKeysPage from '@/pages/openapi/keys';
import CallLogPage from '@/pages/openapi/logs';
import ApiKeyAuditPage from '@/pages/system/apikey-audit';
import AdminDatasetPage from '@/pages/system/dataset';
import AdminDatasetDetailPage from '@/pages/system/dataset/detail';
import LoginLogPage from '@/pages/system/log/login';
import OperationLogPage from '@/pages/system/log/operation';
import ModelPage from '@/pages/system/model';
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

/**
 * 主布局内的业务路由表（tech-design-m1.md 第 6 节映射）。
 * M1~M3 页面均已实现。
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
  { path: '/system/models', element: <ModelPage />, meta: { perm: 'system:model:list' } },
  { path: '/kb/datasets', element: <DatasetListPage />, meta: { perm: 'kb:dataset:list' } },
  // 知识库详情及子页面（FE-11~FE-16）
  {
    path: '/kb/datasets/:id/*',
    element: <DatasetDetailRoutes />,
    meta: { perm: 'kb:dataset:list' },
  },
  { path: '/system/datasets', element: <AdminDatasetPage />, meta: { perm: 'kb:admin:list' } },
  {
    path: '/system/datasets/:id',
    element: <AdminDatasetDetailPage />,
    meta: { perm: 'kb:admin:view' },
  },
  // M3
  { path: '/openapi/keys', element: <ApiKeysPage />, meta: { perm: 'openapi:apikey:manage' } },
  { path: '/openapi/logs', element: <CallLogPage />, meta: { perm: 'openapi:log:list' } },
  { path: '/openapi/docs', element: <ApiDocsPage />, meta: { perm: 'openapi:doc:view' } },
  {
    path: '/system/api-keys',
    element: <ApiKeyAuditPage />,
    meta: { perm: 'openapi:apikey:audit' },
  },
];
