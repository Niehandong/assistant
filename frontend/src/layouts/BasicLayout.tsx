import { LogoutOutlined, UserOutlined } from '@ant-design/icons';
import { ProLayout } from '@ant-design/pro-components';
import { useQueryClient } from '@tanstack/react-query';
import { Dropdown } from 'antd';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import BrandMark from '@/components/BrandMark';
import { renderMenuIcon } from '@/components/menuIcons';
import { useAuthStore } from '@/stores/auth';
import { toLayoutRoutes } from '@/utils/menu';

export default function BasicLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const menus = useAuthStore((s) => s.menus);

  const handleLogout = async () => {
    // 先发起登出再立即跳转，避免状态清空后路由守卫把当前页写进 redirect
    const done = useAuthStore.getState().logout();
    navigate('/login', { replace: true });
    await done;
    queryClient.clear();
  };

  return (
    <ProLayout
      title="知识库平台"
      logo={<BrandMark size={26} />}
      token={{
        bgLayout: '#F5F7F6',
        header: {
          colorBgHeader: '#1E2A32',
          colorHeaderTitle: '#FFFFFF',
          colorTextMenu: 'rgba(255,255,255,0.75)',
          colorTextMenuSelected: '#FFFFFF',
          colorTextRightActionsItem: 'rgba(255,255,255,0.85)',
        },
        sider: {
          colorBgMenuItemSelected: 'rgba(14, 110, 110, 0.08)',
          colorTextMenuSelected: '#0E6E6E',
        },
        pageContainer: {
          paddingBlockPageContainerContent: 20,
          paddingInlinePageContainerContent: 24,
        },
      }}
      layout="mix"
      fixSiderbar
      location={{ pathname: location.pathname }}
      route={{ path: '/', routes: toLayoutRoutes(menus) }}
      menuDataRender={(items) =>
        items.map(function mapIcon(item): typeof item {
          return {
            ...item,
            icon: renderMenuIcon(typeof item.icon === 'string' ? item.icon : null),
            children: item.children?.map(mapIcon),
          };
        })
      }
      menuItemRender={(item, dom) => (item.path ? <Link to={item.path}>{dom}</Link> : dom)}
      avatarProps={{
        icon: <UserOutlined />,
        size: 'small',
        title: user?.name ?? user?.username,
        render: (_, dom) => (
          <Dropdown
            menu={{
              items: [
                { key: 'profile', icon: <UserOutlined />, label: '个人中心' },
                { key: 'logout', icon: <LogoutOutlined />, label: '退出登录' },
              ],
              onClick: ({ key }) => {
                if (key === 'profile') navigate('/profile');
                if (key === 'logout') void handleLogout();
              },
            }}
          >
            {dom}
          </Dropdown>
        ),
      }}
    >
      <Outlet />
    </ProLayout>
  );
}
