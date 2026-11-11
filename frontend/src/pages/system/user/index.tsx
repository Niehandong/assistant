import { PlusOutlined } from '@ant-design/icons';
import { useTableError } from '@/hooks/useTableError';
import { ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components';
import { App, Button, Card, Empty, Result, Skeleton, Space, Tag, Tree } from 'antd';
import type { DataNode } from 'antd/es/tree';
import { useMemo, useRef, useState } from 'react';
import { Access } from '@/access/Access';
import { useOrgOptions } from '@/hooks/useOrgOptions';
import { userApi } from '@/services/iam';
import type { OrgOption, UserCreateResult, UserItem } from '@/services/types/iam-contract';
import { useAuthStore } from '@/stores/auth';
import { formatDateTime } from '@/utils/format';
import { isManageable } from '@/utils/orgTree';
import AssignRolesModal from './components/AssignRolesModal';
import InitialPasswordModal from './components/InitialPasswordModal';
import ResetPasswordModal from './components/ResetPasswordModal';
import UserFormModal from './components/UserFormModal';
import { describeImpact } from './impact';

const toTreeData = (nodes: OrgOption[]): DataNode[] =>
  nodes.map((n) => ({
    key: n.id,
    title: n.status === 'disabled' ? `${n.name}（已停用）` : n.name,
    children: toTreeData(n.children ?? []),
  }));

type Dialog =
  | { type: 'form'; user?: UserItem }
  | { type: 'assign'; user: UserItem }
  | { type: 'reset'; user: UserItem }
  | { type: 'password'; title: string; username: string; password: string }
  | null;

export default function UserPage() {
  const actionRef = useRef<ActionType>();
  const { wrap, locale } = useTableError(actionRef);
  const { modal, message } = App.useApp();
  const meId = useAuthStore((s) => s.user?.id);
  const [orgId, setOrgId] = useState<number | undefined>();
  const [dialog, setDialog] = useState<Dialog>(null);
  const orgs = useOrgOptions();
  const treeData = useMemo(() => toTreeData(orgs.data ?? []), [orgs.data]);
  const reload = () => actionRef.current?.reload();

  /** 停用/删除前取影响提示（失败时按降级文案处理） */
  const confirmDanger = async (
    user: UserItem,
    title: string,
    action: () => Promise<unknown>,
    okText: string,
  ) => {
    const impact = await userApi.impact(user.id).catch(() => null);
    modal.confirm({
      title,
      content: describeImpact(impact),
      okText,
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await action();
          void message.success('操作成功');
          reload();
        } catch {
          // 错误提示由请求拦截器统一处理，这里避免未捕获的 Promise 异常
        }
      },
    });
  };

  const toggleStatus = (u: UserItem) => {
    if (u.status === 'enabled') {
      void confirmDanger(
        u,
        `确认停用用户「${u.name}」？停用后其会话立即失效。`,
        () => userApi.setStatus(u.id, { status: 'disabled', version: u.version }),
        '停用',
      );
    } else {
      modal.confirm({
        title: `确认启用用户「${u.name}」？`,
        onOk: async () => {
          try {
            await userApi.setStatus(u.id, { status: 'enabled', version: u.version });
            void message.success('已启用');
            reload();
          } catch {
            // 错误提示由请求拦截器统一处理
          }
        },
      });
    }
  };

  const remove = (u: UserItem) =>
    void confirmDanger(
      u,
      `确认删除用户「${u.name}」？删除后不可恢复。`,
      () => userApi.remove(u.id),
      '删除',
    );

  const columns: ProColumns<UserItem>[] = [
    { title: '账号', dataIndex: 'username', width: 120 },
    { title: '姓名', dataIndex: 'name', width: 100 },
    { title: '所属组织', dataIndex: 'org_name', search: false, width: 140 },
    {
      title: '所属公司',
      dataIndex: 'company_name',
      search: false,
      width: 140,
      renderText: (v) => v ?? '-',
    },
    {
      title: '角色',
      dataIndex: 'roles',
      search: false,
      width: 200,
      render: (_, r) =>
        (r.roles ?? []).length > 0
          ? (r.roles ?? []).map((x) => <Tag key={x.id}>{x.name}</Tag>)
          : '-',
    },
    { title: '手机号', dataIndex: 'mobile', width: 120, renderText: (v) => v ?? '-' },
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
      width: 300,
      render: (_, u) => {
        // 只读用户行（5.2.0a，如 SELF 看到的本人账号）不显示编辑/重置密码/分配角色/停用/删除
        if (!isManageable(u)) return <span style={{ color: '#999' }}>只读</span>;
        const isSelf = u.id === meId;
        return (
          <Space size={0} wrap>
            <Access code="system:user:update">
              <Button type="link" size="small" onClick={() => setDialog({ type: 'form', user: u })}>
                编辑
              </Button>
            </Access>
            <Access code="system:user:assign">
              <Button
                type="link"
                size="small"
                onClick={() => setDialog({ type: 'assign', user: u })}
              >
                分配角色
              </Button>
            </Access>
            <Access code="system:user:reset_pwd">
              <Button
                type="link"
                size="small"
                onClick={() => setDialog({ type: 'reset', user: u })}
              >
                重置密码
              </Button>
            </Access>
            {!isSelf && !u.is_builtin && (
              <Access code="system:user:status">
                <Button type="link" size="small" onClick={() => toggleStatus(u)}>
                  {u.status === 'enabled' ? '停用' : '启用'}
                </Button>
              </Access>
            )}
            {!isSelf && !u.is_builtin && (
              <Access code="system:user:delete">
                <Button type="link" size="small" danger onClick={() => remove(u)}>
                  删除
                </Button>
              </Access>
            )}
          </Space>
        );
      },
    },
  ];

  let tree;
  if (orgs.isLoading) tree = <Skeleton active />;
  else if (orgs.isError)
    tree = (
      <Result
        status="error"
        title="组织加载失败"
        extra={<Button onClick={() => void orgs.refetch()}>重试</Button>}
      />
    );
  else if (treeData.length === 0) tree = <Empty description="暂无组织" />;
  else
    tree = (
      <Tree
        treeData={treeData}
        defaultExpandAll
        selectedKeys={orgId ? [orgId] : []}
        onSelect={(keys) => setOrgId(keys.length ? (keys[0] as number) : undefined)}
      />
    );

  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
      <Card
        title="组织"
        size="small"
        style={{ width: 260, flexShrink: 0 }}
        extra={
          <Button type="link" size="small" disabled={!orgId} onClick={() => setOrgId(undefined)}>
            全部
          </Button>
        }
      >
        {tree}
      </Card>
      <div style={{ flex: 1, minWidth: 0 }}>
        <ProTable<UserItem>
          onRequestError={() => undefined} // 错误提示由请求拦截器统一处理，避免未捕获异常
          headerTitle="用户管理"
          rowKey="id"
          actionRef={actionRef}
          columns={columns}
          params={{ orgId }}
          scroll={{ x: 1500 }}
          pagination={{ defaultPageSize: 20, showSizeChanger: true }}
          locale={locale}
          request={wrap(async (params) => {
            const res = await userApi.list({
              page: params.current,
              page_size: params.pageSize,
              org_id: params.orgId as number | undefined,
              username: params.username || undefined,
              name: params.name || undefined,
              mobile: params.mobile || undefined,
              status: params.status || undefined,
            });
            return { data: res.items, total: res.total, success: true };
          })}
          toolBarRender={() => [
            <Access key="create" code="system:user:create">
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setDialog({ type: 'form' })}
              >
                新增用户
              </Button>
            </Access>,
          ]}
        />
      </div>
      {dialog?.type === 'form' && (
        <UserFormModal
          editing={dialog.user}
          onClose={() => setDialog(null)}
          onUpdated={() => {
            setDialog(null);
            reload();
          }}
          onCreated={(r: UserCreateResult) => {
            reload();
            setDialog(
              r.initial_password
                ? {
                    type: 'password',
                    title: '用户已创建',
                    username: r.user.username,
                    password: r.initial_password,
                  }
                : null,
            );
          }}
        />
      )}
      {dialog?.type === 'assign' && (
        <AssignRolesModal
          user={dialog.user}
          onClose={() => setDialog(null)}
          onDone={() => {
            setDialog(null);
            reload();
          }}
        />
      )}
      {dialog?.type === 'reset' && (
        <ResetPasswordModal
          user={dialog.user}
          onClose={() => setDialog(null)}
          onDone={(password) => {
            const u = dialog.user;
            if (password) {
              setDialog({ type: 'password', title: '密码已重置', username: u.username, password });
            } else {
              void message.success('密码已重置');
              setDialog(null);
            }
          }}
        />
      )}
      {dialog?.type === 'password' && (
        <InitialPasswordModal
          title={dialog.title}
          username={dialog.username}
          password={dialog.password}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  );
}
