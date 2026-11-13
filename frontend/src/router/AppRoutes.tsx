import { Spin } from 'antd';
import { Suspense } from 'react';
import { Route, Routes } from 'react-router-dom';
import BasicLayout from '@/layouts/BasicLayout';
import ChangePasswordPage from '@/pages/auth/change-password';
import LoginPage from '@/pages/auth/login';
import ProfilePage from '@/pages/auth/profile';
import ForbiddenPage from '@/pages/exception/403';
import NotFoundPage from '@/pages/exception/404';
import HomeRedirect from '@/pages/home';
import { RequireAuth, RequirePerm } from './guards';
import { businessRoutes } from './routes';

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      {/* 改密页独立于主布局（强制改密时不展示菜单） */}
      <Route
        path="/change-password"
        element={
          <RequireAuth>
            <ChangePasswordPage />
          </RequireAuth>
        }
      />
      <Route
        element={
          <RequireAuth>
            <BasicLayout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<HomeRedirect />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/403" element={<ForbiddenPage />} />
        <Route path="/404" element={<NotFoundPage />} />
        {businessRoutes.map((r) => (
          <Route
            key={r.path}
            path={r.path}
            element={
              <RequirePerm perm={r.meta?.perm}>
                <Suspense fallback={<Spin style={{ display: 'block', margin: '80px auto' }} />}>
                  {r.element}
                </Suspense>
              </RequirePerm>
            }
          />
        ))}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
