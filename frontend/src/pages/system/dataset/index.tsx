import { SwapOutlined } from '@ant-design/icons';
import { ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components';
import { Button, Space, Switch, Tag, Typography } from 'antd';
import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Access } from '@/access/Access';
import OrgTreeSelect from '@/components/OrgTreeSelect';
import { useTableError } from '@/hooks/useTableError';
import { adminDatasetApi } from '@/services/kb';
import type { AdminDatasetItem } from '@/services/types/kb-contract';
import { formatDateTime } from '@/utils/format';
import { CHUNK_MODE_LABEL, CHUNK_MODE_UNSET_TEXT } from '../../kb/list/logic';
import AdminTransferModal from './components/AdminTransferModal';
import BatchTransferModal from './components/BatchTransferModal';
import {
  ADMIN_PAGE_SIZE,
  OWNER_STATUS_OPTIONS,
  buildAdminQuery,
  orgText,
  ownerStatusTag,
  segmentText,
  type AdminFilters,
} from './logic';

type Dialog = { type: 'transfer'; item: AdminDatasetItem } | { type: 'batch' } | null;

/** 知识库管理（管理视图）列表：只读审计 + 转移所有权 */
export default function AdminDatasetPage() {
  const actionRef = useRef<ActionType>();
  const { wrap, locale } = useTableError(actionRef);
  const [pending, setPending] = useState(false);
  const [dialog, setDialog] = useState<Dialog>(null);
  const reload = () => actionRef.current?.reload();

  const columns: ProColumns<AdminDatasetItem>[] = [
    // 查询条件
    {
      title: '名称',
      dataIndex: 'keyword',
      hideInTable: true,
      fieldProps: { placeholder: '按名称搜索' },
    },
    {
      title: '所有者',
      dataIndex: 'owner_keyword',
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
      title: '所有者状态',
      dataIndex: 'owner_status',
      hideInTable: true,
      valueType: 'select',
      fieldProps: { options: OWNER_STATUS_OPTIONS, allowClear: true },
    },
    // 列表列
    {
      title: '名称',
      dataIndex: 'name',
      search: false,
      width: 200,
      ellipsis: true,
      render: (_, r) => <Link to={`/system/datasets/${r.id}`}>{r.name}</Link>,
    },
    {
      title: '所有者',
      dataIndex: ['owner', 'name'],
      search: false,
      width: 160,
      render: (_, r) => {
        const tag = ownerStatusTag(r.owner.status);
        return (
          <Space size={4} wrap>
            <span>{r.owner.name}</span>
            {tag && <Tag color={r.owner.status === 'deleted' ? 'error' : 'warning'}>{tag}</Tag>}
          </Space>
        );
      },
    },
    {
      title: '所属公司/部门',
      search: false,
      width: 200,
      ellipsis: true,
      render: (_, r) => orgText(r),
    },
    {
      title: '分段方式',
      dataIndex: 'chunk_mode',
      search: false,
      width: 100,
      renderText: (v: AdminDatasetItem['chunk_mode']) =>
        v ? CHUNK_MODE_LABEL[v] : CHUNK_MODE_UNSET_TEXT,
    },
    { title: '文档数', dataIndex: 'doc_count', search: false, width: 80 },
    { title: '分段数', search: false, width: 150, render: (_, r) => segmentText(r) },
    { title: '分配数', dataIndex: 'assignment_count', search: false, width: 80 },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      search: false,
      width: 170,
      renderText: (v: string) => formatDateTime(v),
    },
    {
      title: '最近更新',
      dataIndex: 'updated_at',
      search: false,
      width: 170,
      renderText: (v: string) => formatDateTime(v),
    },
    {
      title: '操作',
      valueType: 'option',
      fixed: 'right',
      width: 140,
      render: (_, r) => (
        <Space size={0}>
          <Access code="kb:admin:view">
            <Link to={`/system/datasets/${r.id}`}>查看</Link>
          </Access>
          <Access code="kb:admin:transfer">
            <Button
              type="link"
              size="small"
              onClick={() => setDialog({ type: 'transfer', item: r })}
            >
              转移
            </Button>
          </Access>
        </Space>
      ),
    },
  ];

  return (
    <>
      <ProTable<AdminDatasetItem, AdminFilters>
        onRequestError={() => undefined}
        headerTitle="知识库管理"
        rowKey="id"
        actionRef={actionRef}
        columns={columns}
        params={{ pending_handover: pending }}
        scroll={{ x: 1500 }}
        pagination={{ defaultPageSize: ADMIN_PAGE_SIZE, showSizeChanger: false }}
        search={{ labelWidth: 'auto', defaultCollapsed: false }}
        locale={locale ?? { emptyText: pending ? '没有待交接的知识库' : '没有符合条件的知识库' }}
        request={wrap(async (params: AdminFilters & { current?: number; pageSize?: number }) => {
          const res = await adminDatasetApi.list(
            buildAdminQuery(params, params.current ?? 1, params.pageSize ?? ADMIN_PAGE_SIZE),
          );
          return { data: res.items, total: res.total, success: true };
        })}
        toolBarRender={() => [
          <Space key="pending" size={6}>
            <Switch aria-label="待交接" checked={pending} onChange={setPending} />
            <Typography.Text>待交接（所有者已停用/删除）</Typography.Text>
          </Space>,
          <Access key="batch" code="kb:admin:transfer">
            <Button icon={<SwapOutlined />} onClick={() => setDialog({ type: 'batch' })}>
              批量转移
            </Button>
          </Access>,
        ]}
      />
      {dialog?.type === 'transfer' && (
        <AdminTransferModal
          dataset={dialog.item}
          onClose={() => setDialog(null)}
          onTransferred={() => {
            setDialog(null);
            reload();
          }}
        />
      )}
      {dialog?.type === 'batch' && (
        <BatchTransferModal onClose={() => setDialog(null)} onDone={reload} />
      )}
    </>
  );
}
