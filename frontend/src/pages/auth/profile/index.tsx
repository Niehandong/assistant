import { Button, Card, Descriptions, Empty } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/stores/auth';
import { formatDateTime } from '@/utils/format';

export default function ProfilePage() {
  const user = useAuthStore((s) => s.user);
  const loading = useAuthStore((s) => s.loading);
  const navigate = useNavigate();

  return (
    <Card
      title="个人中心"
      loading={loading && !user}
      extra={
        <Button type="primary" onClick={() => navigate('/change-password')}>
          修改密码
        </Button>
      }
    >
      {user ? (
        <Descriptions column={2} bordered>
          <Descriptions.Item label="账号">{user.username}</Descriptions.Item>
          <Descriptions.Item label="姓名">{user.name}</Descriptions.Item>
          <Descriptions.Item label="所属组织">{user.org_name}</Descriptions.Item>
          <Descriptions.Item label="所属公司">{user.company_name ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="手机号">{user.mobile ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="邮箱">{user.email ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="最近登录">
            {formatDateTime(user.last_login_at)}
          </Descriptions.Item>
        </Descriptions>
      ) : (
        <Empty description="暂无用户信息" />
      )}
    </Card>
  );
}
