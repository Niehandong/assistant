import { useTableError } from '@/hooks/useTableError';
import { ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components';
import { App, Button, Tag } from 'antd';
import { useRef, useState } from 'react';
import { logApi } from '@/services/iam';
import type { OperationLogItem } from '@/services/types/iam-contract';
import { formatDateTime } from '@/utils/format';
import { timeRangeColumn } from '../columns';
import {
  ALL_ACTION_VALUE_ENUM,
  MODULE_VALUE_ENUM,
  RESULT_LABEL,
  actionLabel,
  moduleLabel,
} from '../dict';
import { parseRangeParam, toIso } from '../timeRange';
import OpLogDetailDrawer from './components/OpLogDetailDrawer';

export default function OperationLogPage() {
  const actionRef = useRef<ActionType>();
  const { wrap, locale } = useTableError(actionRef);
  const { message } = App.useApp();
  const [detailId, setDetailId] = useState<number | null>(null);

  const columns: ProColumns<OperationLogItem>[] = [
    timeRangeColumn<OperationLogItem>(),
    {
      title: '时间',
      dataIndex: 'occurred_at',
      search: false,
      width: 170,
      renderText: (v: string) => formatDateTime(v),
    },
    {
      title: '操作人',
      dataIndex: 'operator',
      width: 160,
      render: (_, r) =>
        r.operator_name ? `${r.operator_name}（${r.operator_username ?? '-'}）` : '-',
      fieldProps: { placeholder: '姓名或账号' },
    },
    {
      title: '所属公司',
      dataIndex: 'company_name',
      search: false,
      width: 140,
      renderText: (v) => v ?? '-',
    },
    {
      title: '模块',
      dataIndex: 'module',
      valueType: 'select',
      valueEnum: MODULE_VALUE_ENUM,
      width: 100,
      render: (_, r) => moduleLabel(r.module),
    },
    {
      title: '操作类型',
      dataIndex: 'action',
      valueType: 'select',
      valueEnum: ALL_ACTION_VALUE_ENUM,
      width: 110,
      render: (_, r) => actionLabel(r.module, r.action),
    },
    {
      title: '操作对象',
      dataIndex: 'target_name',
      search: false,
      width: 180,
      ellipsis: true,
      renderText: (v) => v ?? '-',
    },
    {
      title: '结果',
      dataIndex: 'result',
      valueType: 'select',
      valueEnum: { success: { text: '成功' }, failure: { text: '失败' } },
      width: 80,
      render: (_, r) => (
        <Tag color={r.result === 'success' ? 'success' : 'error'}>{RESULT_LABEL[r.result]}</Tag>
      ),
    },
    { title: 'IP', dataIndex: 'ip', search: false, width: 130, renderText: (v) => v ?? '-' },
    {
      title: '操作',
      valueType: 'option',
      width: 80,
      fixed: 'right',
      render: (_, r) => (
        <Button type="link" size="small" onClick={() => setDetailId(r.id)}>
          详情
        </Button>
      ),
    },
  ];

  return (
    <>
      <ProTable<OperationLogItem>
        actionRef={actionRef}
        onRequestError={() => undefined} // 错误提示由请求拦截器统一处理，避免未捕获异常
        headerTitle="操作日志"
        rowKey="id"
        columns={columns}
        scroll={{ x: 1200 }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        locale={locale}
        request={wrap(async (params) => {
          const range = parseRangeParam(params.time_range);
          if (range.start === null) {
            void message.warning(range.error);
            return { data: [], total: 0, success: true };
          }
          const res = await logApi.operationList({
            page: params.current,
            page_size: params.pageSize,
            start_time: toIso(range.start),
            end_time: toIso(range.end),
            operator: params.operator || undefined,
            module: params.module || undefined,
            action: params.action || undefined,
            result: params.result || undefined,
          });
          return { data: res.items, total: res.total, success: true };
        })}
      />
      {detailId !== null && <OpLogDetailDrawer id={detailId} onClose={() => setDetailId(null)} />}
    </>
  );
}
