import { Empty } from 'antd';
import { Navigate } from 'react-router-dom';
import { useAuthStore } from '@/stores/auth';
import { findFirstMenuPath } from '@/utils/menu';

/** `/`：重定向到第一个有权限的菜单；没有任何菜单时显示空状态 */
export default function HomeRedirect() {
  const menus = useAuthStore((s) => s.menus);
  const first = findFirstMenuPath(menus);
  if (first) return <Navigate to={first} replace />;
  return <Empty style={{ padding: 64 }} description="暂无可访问的菜单，请联系管理员分配权限" />;
}
