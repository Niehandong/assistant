import { PlusOutlined } from '@ant-design/icons';
import { useTableError } from '@/hooks/useTableError';
import { ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components';
import { App, Button, Space, Tag } from 'antd';
import { useRef, useState } from 'react';
import { Access } from '@/access/Access';
import { roleApi } from '@/services/iam';
import type { RoleItem } from '@/services/types/iam-contract';
import { formatDateTime } from '@/utils/format';
import GrantDrawer from './components/GrantDrawer';
import RoleFormModal from './components/RoleFormModal';
import RoleUsersDrawer from './components/RoleUsersDrawer';
import { DATA_SCOPE_LABEL } from './grantLogic';

type Dialog =
  | { type: 'form'; role?: RoleItem }
  | { type: 'grant'; role: RoleItem }
  | { type: 'users'; role: RoleItem }
  | null;

export default function RolePage() {
  const actionRef = useRef<ActionType>();
  const { wrap, locale } = useTableError(actionRef);
  const { modal, message } = App.useApp();
  const [dialog, setDialog] = useState<Dialog>(null);
  const reload = () => actionRef.current?.reload();

  const remove = (r: RoleItem) =>
    modal.confirm({
      title: `确认删除角色「${r.name}」？`,
      content: '删除后不可恢复；角色仍有关联用户时无法删除。',
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await roleApi.remove(r.id);
          void message.success('已删除');
          reload();
        } catch {
          // 错误提示由请求拦截器统一处理，这里避免未捕获的 Promise 异常
        }
      },
    });

  const columns: ProColumns<RoleItem>[] = [
    { title: '角色名称', dataIndex: 'name', width: 160 },
    { title: '角色编码', dataIndex: 'code', width: 140 },
    {
      title: '类型',
      dataIndex: 'role_type',
      valueType: 'select',
      valueEnum: { group: { text: '集团级' }, company: { text: '公司级' } },
      width: 90,
    },
    {
      title: '所属公司',
      dataIndex: 'owner_company_name',
      search: false,
      width: 140,
      renderText: (v) => v ?? '-',
    },
    {
      title: '数据范围',
      dataIndex: 'data_scope',
      search: false,
      width: 140,
      renderText: (v: RoleItem['data_scope']) => DATA_SCOPE_LABEL[v],
    },
    { title: '用户数', dataIndex: 'user_count', search: false, width: 80 },
    {
      title: '状态',
      dataIndex: 'status',
      valueType: 'select',
      valueEnum: { enabled: { text: '启用' }, disabled: { text: '停用' } },
      width: 80,
      render: (_, r) => (
        <Tag color={r.status === 'enabled' ? 'success' : 'default'}>
          {r.status === 'enabled' ? '启用' : '停用'}
        </Tag>
      ),
    },
    {
      title: '内置',
      dataIndex: 'is_builtin',
      search: false,
      width: 70,
      render: (_, r) => (r.is_builtin ? <Tag color="blue">内置</Tag> : '-'),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      search: false,
      width: 170,
      renderText: (v: string) => formatDateTime(v),
    },
    {
      title: '操作',
      valueType: 'option',
      fixed: 'right',
      width: 240,
      render: (_, r) => (
        <Space size={0} wrap>
          <Button type="link" size="small" onClick={() => setDialog({ type: 'users', role: r })}>
            用户
          </Button>
          {r.editable && (
            <>
              <Access code="system:role:update">
                <Button
                  type="link"
                  size="small"
                  onClick={() => setDialog({ type: 'form', role: r })}
                >
                  编辑
                </Button>
              </Access>
              <Access code="system:role:grant">
                <Button
                  type="link"
                  size="small"
                  onClick={() => setDialog({ type: 'grant', role: r })}
                >
                  授权
                </Button>
              </Access>
              {!r.is_builtin && (
                <Access code="system:role:delete">
                  <Button type="link" size="small" danger onClick={() => remove(r)}>
                    删除
                  </Button>
                </Access>
              )}
            </>
          )}
        </Space>
      ),
    },
  ];

  return (
    <>
      <ProTable<RoleItem>
        onRequestError={() => undefined} // 错误提示由请求拦截器统一处理，避免未捕获异常
        headerTitle="角色管理"
        rowKey="id"
        actionRef={actionRef}
        columns={columns}
        scroll={{ x: 1250 }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        locale={locale}
        request={wrap(async (params) => {
          const res = await roleApi.list({
            page: params.current,
            page_size: params.pageSize,
            name: params.name || undefined,
            code: params.code || undefined,
            role_type: params.role_type || undefined,
            status: params.status || undefined,
          });
          return { data: res.items, total: res.total, success: true };
        })}
        toolBarRender={() => [
          <Access key="create" code="system:role:create">
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setDialog({ type: 'form' })}
            >
              新增角色
            </Button>
          </Access>,
        ]}
      />
      {dialog?.type === 'form' && (
        <RoleFormModal
          editing={dialog.role}
          onClose={() => setDialog(null)}
          onSuccess={() => {
            setDialog(null);
            reload();
          }}
        />
      )}
      {dialog?.type === 'grant' && (
        <GrantDrawer
          role={dialog.role}
          onClose={() => setDialog(null)}
          onSuccess={() => {
            setDialog(null);
            reload();
          }}
        />
      )}
      {dialog?.type === 'users' && (
        <RoleUsersDrawer role={dialog.role} onClose={() => setDialog(null)} />
      )}
    </>
  );
}
