import { Button, Result, Spin } from 'antd';
import ForbiddenPage from '@/pages/exception/403';
import { useEffect, useState, type ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { tokenStore } from '@/api/tokenStore';
import { usePermission } from '@/access/usePermission';
import { useAuthStore } from '@/stores/auth';

export const CHANGE_PASSWORD_PATH = '/change-password';
export const LOGIN_PATH = '/login';

/** 登录态守卫：未登录跳登录；加载 me；must_change_password 只允许改密页 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation();
  const loaded = useAuthStore((s) => s.loaded);
  const user = useAuthStore((s) => s.user);
  const loadMe = useAuthStore((s) => s.loadMe);
  const [error, setError] = useState(false);
  const hasToken = tokenStore.hasToken();

  useEffect(() => {
    if (hasToken && !loaded && !error) {
      loadMe().catch(() => setError(true));
    }
  }, [hasToken, loaded, error, loadMe]);

  if (!hasToken) {
    const redirect = encodeURIComponent(location.pathname + location.search + location.hash);
    return <Navigate to={`${LOGIN_PATH}?redirect=${redirect}`} replace />;
  }
  if (error) {
    return (
      <Result
        status="error"
        title="加载用户信息失败"
        extra={
          <Button type="primary" onClick={() => setError(false)}>
            重试
          </Button>
        }
      />
    );
  }
  if (!loaded || !user) {
    return <Spin fullscreen tip="加载中" />;
  }
  if (user.must_change_password && location.pathname !== CHANGE_PASSWORD_PATH) {
    return <Navigate to={CHANGE_PASSWORD_PATH} replace />;
  }
  return <>{children}</>;
}

/** 路由权限守卫：meta.perm 不满足 → 403 页 */
export function RequirePerm({ perm, children }: { perm?: string | string[]; children: ReactNode }) {
  const can = usePermission();
  if (perm && !can(perm)) return <ForbiddenPage />;
  return <>{children}</>;
}
