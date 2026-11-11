import { useRef } from 'react';
import { useTableError } from '@/hooks/useTableError';
import { ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components';
import { App, Tag } from 'antd';
import { logApi } from '@/services/iam';
import type { LoginLogItem } from '@/services/types/iam-contract';
import { formatDateTime } from '@/utils/format';
import { timeRangeColumn } from '../columns';
import { FAIL_REASON_LABEL, RESULT_LABEL } from '../dict';
import { parseRangeParam, toIso } from '../timeRange';

export default function LoginLogPage() {
  const actionRef = useRef<ActionType>();
  const { wrap, locale } = useTableError(actionRef);
  const { message } = App.useApp();

  const columns: ProColumns<LoginLogItem>[] = [
    timeRangeColumn<LoginLogItem>(),
    {
      title: '登录时间',
      dataIndex: 'login_at',
      search: false,
      width: 170,
      renderText: (v: string) => formatDateTime(v),
    },
    { title: '账号', dataIndex: 'username', width: 130 },
    {
      title: '姓名',
      dataIndex: 'user_name',
      search: false,
      width: 100,
      renderText: (v) => v ?? '-',
    },
    {
      title: '所属公司',
      dataIndex: 'company_name',
      search: false,
      width: 140,
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
    {
      title: '失败原因',
      dataIndex: 'fail_reason',
      search: false,
      width: 200,
      ellipsis: true,
      renderText: (_, r) =>
        r.result === 'success'
          ? '-'
          : ((r.fail_reason ? FAIL_REASON_LABEL[r.fail_reason] : undefined) ??
            r.fail_message ??
            r.fail_reason ??
            '-'),
    },
    { title: 'IP', dataIndex: 'ip', width: 130, renderText: (v) => v ?? '-' },
    {
      title: '终端',
      dataIndex: 'user_agent',
      search: false,
      ellipsis: true,
      width: 220,
      renderText: (v) => v ?? '-',
    },
  ];

  return (
    <ProTable<LoginLogItem>
      actionRef={actionRef}
      onRequestError={() => undefined} // 错误提示由请求拦截器统一处理，避免未捕获异常
      headerTitle="登录日志"
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
        const res = await logApi.loginList({
          page: params.current,
          page_size: params.pageSize,
          start_time: toIso(range.start),
          end_time: toIso(range.end),
          username: params.username || undefined,
          result: params.result || undefined,
          ip: params.ip || undefined,
        });
        return { data: res.items, total: res.total, success: true };
      })}
    />
  );
}
