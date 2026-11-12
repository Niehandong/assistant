import { ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components';
import { App, Button, Space, Tag } from 'antd';
import { useRef, useState } from 'react';
import { Access } from '@/access/Access';
import OrgTreeSelect from '@/components/OrgTreeSelect';
import { useTableError } from '@/hooks/useTableError';
import { auditApi } from '@/services/open';
import type { AuditApiKeyItem, AuditStatus } from '@/services/types/open-contract';
import { formatDateTime } from '@/utils/format';
import { STATUS_COLOR, expiresText, statusLabel } from '../../openapi/keys/logic';
import AuditCallLogDrawer from './components/AuditCallLogDrawer';
import { AUDIT_STATUS_OPTIONS, auditRowActions, auditScopeText, creatorStatusTag } from './logic';

interface Filters {
  creator_keyword?: string;
  org_id?: number;
  status?: AuditStatus;
}

type Drawer = { key: { id: number; name: string } | null } | null;

/** API 密钥审计（管理员，F-17 规则 9）：只读 + 停用 / 删除 */
export default function ApiKeyAuditPage() {
  const actionRef = useRef<ActionType>();
  const { wrap, locale } = useTableError(actionRef);
  const { message, modal } = App.useApp();
  const [drawer, setDrawer] = useState<Drawer>(null);
  const reload = () => actionRef.current?.reload();

  const disable = (r: AuditApiKeyItem) =>
    modal.confirm({
      title: `停用「${r.creator.name}」的密钥「${r.name}」？`,
      content: '停用后创建人无法自行启用，立即生效。',
      okText: '停用',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await auditApi.disable(r.id, { version: r.version });
          void message.success('已停用');
          reload();
        } catch {
          // 错误提示由请求拦截器统一处理
        }
      },
    });

  const remove = (r: AuditApiKeyItem) =>
    modal.confirm({
      title: `删除「${r.creator.name}」的密钥「${r.name}」？`,
      content: '删除后该密钥立即失效且不可恢复。',
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await auditApi.remove(r.id);
          void message.success('已删除');
          reload();
        } catch {
          // 错误提示由请求拦截器统一处理
        }
      },
    });

  const columns: ProColumns<AuditApiKeyItem>[] = [
    {
      title: '创建人',
      dataIndex: 'creator_keyword',
      hideInTable: true,
      fieldProps: { placeholder: '姓名或账号' },
    },
    {
      title: '所属组织',
      dataIndex: 'org_id',
      hideInTable: true,
      renderFormItem: (_, { value, onChange }) => (
        <OrgTreeSelect
          value={value as number | undefined}
          onChange={(v) => onChange?.(v as number | undefined)}
          placeholder="选择组织（含下级）"
        />
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      valueType: 'select',
      fieldProps: { options: AUDIT_STATUS_OPTIONS, allowClear: true },
      width: 140,
      render: (_, r) => <Tag color={STATUS_COLOR[r.status]}>{statusLabel(r.status)}</Tag>,
    },
    { title: '密钥名称', dataIndex: 'name', search: false, width: 160, ellipsis: true },
    { title: '密钥', dataIndex: 'key_masked', search: false, width: 130 },
    {
      title: '创建人',
      search: false,
      width: 170,
      render: (_, r) => {
        const tag = creatorStatusTag(r.creator.status);
        return (
          <Space size={4} wrap>
            <span>
              {r.creator.name}（{r.creator.username}）
            </span>
            {tag && <Tag color="warning">{tag}</Tag>}
          </Space>
        );
      },
    },
    {
      title: '所属公司/部门',
      search: false,
      width: 180,
      ellipsis: true,
      render: (_, r) =>
        r.dept.id === r.company.id ? r.company.name : `${r.company.name} / ${r.dept.name}`,
    },
    { title: '检索范围', search: false, width: 100, render: (_, r) => auditScopeText(r) },
    {
      title: '当前可检索',
      dataIndex: 'accessible_dataset_count',
      search: false,
      width: 100,
      renderText: (v: number) => `${v} 个`,
    },
    { title: '过期时间', search: false, width: 170, render: (_, r) => expiresText(r.expires_at) },
    { title: '限流', search: false, width: 100, render: (_, r) => `${r.rate_limit_per_min} 次/分` },
    {
      title: '近 7 天',
      search: false,
      width: 130,
      render: (_, r) => `调用 ${r.calls_7d} / 失败 ${r.failures_7d}`,
    },
    {
      title: '最近调用',
      search: false,
      width: 170,
      renderText: (_, r) => formatDateTime(r.last_used_at),
    },
    {
      title: '创建时间',
      search: false,
      width: 170,
      renderText: (_, r) => formatDateTime(r.created_at),
    },
    {
      title: '操作',
      valueType: 'option',
      fixed: 'right',
      width: 200,
      render: (_, r) => {
        const a = auditRowActions(r);
        return (
          <Space size={0}>
            <Access code="openapi:apikey:audit">
              {a.disable && (
                <Button type="link" size="small" onClick={() => disable(r)}>
                  停用
                </Button>
              )}
              {a.remove && (
                <Button type="link" size="small" danger onClick={() => remove(r)}>
                  删除
                </Button>
              )}
              {a.logs && (
                <Button
                  type="link"
                  size="small"
                  onClick={() => setDrawer({ key: { id: r.id, name: r.name } })}
                >
                  调用日志
                </Button>
              )}
            </Access>
          </Space>
        );
      },
    },
  ];

  return (
    <>
      <ProTable<AuditApiKeyItem, Filters>
        onRequestError={() => undefined}
        headerTitle="API 密钥审计"
        rowKey="id"
        actionRef={actionRef}
        columns={columns}
        scroll={{ x: 1700 }}
        pagination={{ defaultPageSize: 20, showSizeChanger: false }}
        search={{ labelWidth: 'auto', defaultCollapsed: false }}
        locale={locale ?? { emptyText: '没有符合条件的密钥' }}
        request={wrap(async (params: Filters & { current?: number; pageSize?: number }) => {
          const res = await auditApi.list({
            page: params.current ?? 1,
            page_size: params.pageSize ?? 20,
            creator_keyword: params.creator_keyword?.trim() || undefined,
            org_id: params.org_id || undefined,
            status: params.status || undefined,
          });
          return { data: res.items, total: res.total, success: true };
        })}
        toolBarRender={() => [
          <Access key="all" code="openapi:apikey:audit">
            <Button onClick={() => setDrawer({ key: null })}>全部调用日志</Button>
          </Access>,
        ]}
      />
      {drawer && <AuditCallLogDrawer apiKey={drawer.key} onClose={() => setDrawer(null)} />}
    </>
  );
}
