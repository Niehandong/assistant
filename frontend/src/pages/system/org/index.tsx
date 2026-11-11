import { PlusOutlined } from '@ant-design/icons';
import { useTableError } from '@/hooks/useTableError';
import { ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components';
import { App, Button, Space, Tag, Tooltip } from 'antd';
import { useRef, useState } from 'react';
import { Access } from '@/access/Access';
import { notifyError } from '@/utils/notify';
import { ORG_OPTIONS_KEY } from '@/hooks/useOrgOptions';
import { orgApi } from '@/services/iam';
import type { OrgNode } from '@/services/types/iam-contract';
import { ApiError } from '@/utils/error';
import {
  collectAllIds,
  ORG_TYPE_LABEL,
  getBlockedReason,
  isManageable,
  pruneEmptyChildren,
} from '@/utils/orgTree';
import { formatDateTime } from '@/utils/format';
import { useQueryClient } from '@tanstack/react-query';
import MoveOrgModal from './components/MoveOrgModal';
import OrgFormModal from './components/OrgFormModal';

type FormState = { mode: 'create'; parent?: OrgNode } | { mode: 'edit'; node: OrgNode } | null;

export default function OrgPage() {
  const actionRef = useRef<ActionType>();
  const { wrap, locale } = useTableError(actionRef);
  const { modal, message } = App.useApp();
  const queryClient = useQueryClient();
  const [formState, setFormState] = useState<FormState>(null);
  const [moving, setMoving] = useState<OrgNode | null>(null);
  const [expandedKeys, setExpandedKeys] = useState<number[]>([]);
  // 当前可见的全部节点 id：上级不可见的节点（如子公司管理员的本公司节点）不能调整上级（403101）
  const [visibleIds, setVisibleIds] = useState<Set<number>>(new Set());

  const reload = () => {
    void queryClient.invalidateQueries({ queryKey: [ORG_OPTIONS_KEY] });
    actionRef.current?.reload();
  };

  const toggleStatus = (node: OrgNode) => {
    const disabling = node.status === 'enabled';
    modal.confirm({
      title: disabling ? `确认停用「${node.name}」？` : `确认启用「${node.name}」？`,
      content: disabling
        ? '停用后，该组织及其下级组织的用户将立即被强制下线且无法登录。'
        : '启用后，之前被强制下线的用户需要重新登录。',
      okButtonProps: { danger: disabling },
      onOk: async () => {
        try {
          await orgApi.setStatus(node.id, {
            status: disabling ? 'disabled' : 'enabled',
            version: node.version,
          });
          void message.success(disabling ? '已停用' : '已启用');
          reload();
        } catch {
          // 错误提示由请求拦截器统一处理，这里避免未捕获的 Promise 异常
        }
      },
    });
  };

  /** 删除失败提示：409106 展示归属该公司的角色名单，其余显示后端 message（含 403102） */
  const showDeleteError = (err: unknown) => {
    if (err instanceof ApiError && err.code === 409106) {
      const data = err.data as { roles?: string[]; total?: number } | null;
      const roles = data?.roles ?? [];
      const total = data?.total ?? roles.length;
      modal.warning({
        title: '该公司下仍有公司级角色，不能删除',
        content: (
          <div>
            <p>请先删除或迁移以下角色（共 {total} 个）：</p>
            <ul style={{ paddingLeft: 20, margin: 0 }}>
              {roles.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
            {total > roles.length && <p>……等 {total} 个</p>}
          </div>
        ),
      });
      return;
    }
    notifyError(err);
  };

  const remove = (node: OrgNode) => {
    modal.confirm({
      title: `确认删除「${node.name}」？`,
      content: '删除后不可恢复。组织下存在下级组织、用户或知识库时无法删除。',
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await orgApi.remove(node.id);
          void message.success('已删除');
          reload();
        } catch (err) {
          showDeleteError(err);
        }
      },
    });
  };

  /** 受保护时置灰并用 Tooltip 展示后端给出的文案（不隐藏） */
  const renderGuarded = (
    text: string,
    reason: string | null,
    onClick: () => void,
    danger = false,
  ) =>
    reason ? (
      <Tooltip title={reason}>
        <span style={{ display: 'inline-block' }}>
          <Button type="link" size="small" danger={danger} disabled>
            {text}
          </Button>
        </span>
      </Tooltip>
    ) : (
      <Button type="link" size="small" danger={danger} onClick={onClick}>
        {text}
      </Button>
    );

  const columns: ProColumns<OrgNode>[] = [
    { title: '组织名称', dataIndex: 'name', width: 240 },
    {
      title: '类型',
      dataIndex: 'org_type',
      search: false,
      width: 80,
      render: (_, r) => ORG_TYPE_LABEL[r.org_type],
    },
    { title: '编码', dataIndex: 'code', search: false, width: 140 },
    {
      title: '负责人',
      dataIndex: 'leader_name',
      search: false,
      width: 120,
      renderText: (v) => v ?? '-',
    },
    { title: '显示顺序', dataIndex: 'sort_order', search: false, width: 90 },
    {
      title: '状态',
      dataIndex: 'status',
      valueType: 'select',
      valueEnum: { enabled: { text: '启用' }, disabled: { text: '停用' } },
      width: 150,
      render: (_, r) => (
        <Space size={4}>
          <Tag color={r.status === 'enabled' ? 'success' : 'default'}>
            {r.status === 'enabled' ? '启用' : '停用'}
          </Tag>
          {r.status === 'enabled' && r.effective_status === 'disabled' && (
            <Tag color="warning">上级已停用</Tag>
          )}
        </Space>
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
      width: 330,
      fixed: 'right',
      render: (_, r) => {
        // 只读节点（5.2.0a，如 SELF 的本人组织链）不显示任何管理操作
        if (!isManageable(r)) return <span style={{ color: '#999' }}>只读</span>;
        const isGroup = r.org_type === 'group';
        return (
          <Space size={0} wrap>
            <Access code="system:org:create">
              <Button
                type="link"
                size="small"
                onClick={() => setFormState({ mode: 'create', parent: r })}
              >
                新增下级
              </Button>
            </Access>
            <Access code="system:org:update">
              <Button
                type="link"
                size="small"
                onClick={() => setFormState({ mode: 'edit', node: r })}
              >
                编辑
              </Button>
              {!isGroup && visibleIds.has(r.parent_id) && (
                <Button type="link" size="small" onClick={() => setMoving(r)}>
                  移动
                </Button>
              )}
              {renderGuarded(
                r.status === 'enabled' ? '停用' : '启用',
                getBlockedReason(r, 'disable'),
                () => toggleStatus(r),
              )}
            </Access>
            <Access code="system:org:delete">
              {renderGuarded('删除', getBlockedReason(r, 'delete'), () => remove(r), true)}
            </Access>
          </Space>
        );
      },
    },
  ];

  return (
    <>
      <ProTable<OrgNode>
        onRequestError={() => undefined} // 错误提示由请求拦截器统一处理，避免未捕获异常
        headerTitle="组织管理"
        rowKey="id"
        actionRef={actionRef}
        columns={columns}
        pagination={false}
        scroll={{ x: 1350 }}
        expandable={{
          expandedRowKeys: expandedKeys,
          onExpandedRowsChange: (keys) => setExpandedKeys(keys as number[]),
        }}
        locale={locale}
        request={wrap(async (params) => {
          const tree = await orgApi.tree({
            name: params.name || undefined,
            status: params.status || undefined,
          });
          const data = pruneEmptyChildren(tree);
          const ids = collectAllIds(data);
          setExpandedKeys(ids);
          setVisibleIds(new Set(ids));
          return { data, success: true };
        })}
        toolBarRender={() => [
          <Access key="create" code="system:org:create">
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setFormState({ mode: 'create' })}
            >
              新增组织
            </Button>
          </Access>,
        ]}
      />
      {formState && (
        <OrgFormModal
          editing={formState.mode === 'edit' ? formState.node : undefined}
          parent={
            formState.mode === 'create' && formState.parent
              ? {
                  id: formState.parent.id,
                  org_type: formState.parent.org_type,
                  name: formState.parent.name,
                }
              : undefined
          }
          onClose={() => setFormState(null)}
          onSuccess={() => {
            setFormState(null);
            reload();
          }}
        />
      )}
      {moving && (
        <MoveOrgModal
          node={moving}
          onClose={() => setMoving(null)}
          onSuccess={() => {
            setMoving(null);
            reload();
          }}
        />
      )}
    </>
  );
}
