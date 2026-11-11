import { useRef } from 'react';
import { useTableError } from '@/hooks/useTableError';
import { ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components';
import { Drawer, Tag } from 'antd';
import { roleApi } from '@/services/iam';
import type { RoleItem, UserItem } from '@/services/types/iam-contract';

const columns: ProColumns<UserItem>[] = [
  { title: '账号', dataIndex: 'username' },
  { title: '姓名', dataIndex: 'name' },
  { title: '所属组织', dataIndex: 'org_name' },
  {
    title: '状态',
    dataIndex: 'status',
    render: (_, r) => (
      <Tag color={r.status === 'enabled' ? 'success' : 'default'}>
        {r.status === 'enabled' ? '启用' : '停用'}
      </Tag>
    ),
  },
];

export default function RoleUsersDrawer({
  role,
  onClose,
}: {
  role: RoleItem;
  onClose: () => void;
}) {
  const actionRef = useRef<ActionType>();
  const { wrap, locale } = useTableError(actionRef);
  return (
    <Drawer open width={640} title={`角色用户：${role.name}`} onClose={onClose} destroyOnClose>
      <ProTable<UserItem>
        actionRef={actionRef}
        onRequestError={() => undefined} // 错误提示由请求拦截器统一处理，避免未捕获异常
        rowKey="id"
        columns={columns}
        search={false}
        options={false}
        toolBarRender={false}
        pagination={{ defaultPageSize: 20 }}
        locale={locale}
        request={wrap(async (params) => {
          const res = await roleApi.users(role.id, {
            page: params.current,
            page_size: params.pageSize,
          });
          return { data: res.items, total: res.total, success: true };
        })}
      />
    </Drawer>
  );
}
