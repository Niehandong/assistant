import { useQuery } from '@tanstack/react-query';
import { ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components';
import { App, Select, Switch, Tag, Tooltip, Typography } from 'antd';
import { useRef } from 'react';
import { useTableError } from '@/hooks/useTableError';
import { apiKeyApi, auditApi, callLogApi } from '@/services/open';
import type { AuditCallLogItem, CallResult } from '@/services/types/open-contract';
import { formatDateTime } from '@/utils/format';
import DatasetOptionSelect from './DatasetOptionSelect';
import {
  CALL_RESULT_OPTIONS,
  callResultColor,
  callResultLabel,
  defaultLogRange,
  isLogDateDisabled,
  parseLogRange,
  truncateQuery,
} from './callLog';

interface Props {
  /** mine：本人密钥的日志；audit：管理员按数据范围查看他人日志 */
  mode: 'mine' | 'audit';
  /** 预填 / 固定的密钥 ID（mine 为预填可改；audit 抽屉中为固定过滤） */
  apiKeyId?: number;
  /** audit 模式：显示"含无法识别密钥"开关（仅"全部调用日志"且 capabilities 为 true） */
  showUnknownSwitch?: boolean;
  headerTitle?: string;
}

interface Filters {
  time_range?: unknown;
  api_key_id?: number;
  dataset_id?: number;
  result?: CallResult;
  creator_keyword?: string;
  include_unknown?: boolean;
  fixed_key?: number;
}

function KeySelect({
  value,
  onChange,
}: {
  value?: number;
  onChange?: (v: number | undefined) => void;
}) {
  const { data, isFetching } = useQuery({
    queryKey: ['open-key-select'],
    queryFn: () => apiKeyApi.list({ page: 1, page_size: 100 }),
    staleTime: 30_000,
  });
  return (
    <Select
      allowClear
      showSearch
      optionFilterProp="label"
      loading={isFetching}
      value={value}
      onChange={(v) => onChange?.(v)}
      placeholder="全部密钥"
      options={(data?.items ?? []).map((k) => ({
        value: k.id,
        label: `${k.name}（${k.key_masked}）`,
      }))}
    />
  );
}

/** 调用日志通用表格（FE-19 / FE-20） */
export default function CallLogTable({ mode, apiKeyId, showUnknownSwitch, headerTitle }: Props) {
  const actionRef = useRef<ActionType>();
  const { wrap, locale } = useTableError(actionRef);
  const { message } = App.useApp();
  const audit = mode === 'audit';
  const fixedKey = audit && apiKeyId !== undefined;

  const columns: ProColumns<AuditCallLogItem>[] = [
    {
      title: '时间范围',
      dataIndex: 'time_range',
      valueType: 'dateTimeRange',
      hideInTable: true,
      colSize: 1.6,
      initialValue: defaultLogRange(),
      fieldProps: {
        allowClear: false,
        disabledDate: (
          current: Parameters<typeof isLogDateDisabled>[0],
          info?: { from?: Parameters<typeof isLogDateDisabled>[1] },
        ) => isLogDateDisabled(current, info?.from),
      },
      formItemProps: { rules: [{ required: true, message: '请选择时间范围' }] },
      tooltip: '默认近 7 天，最长 90 天',
    },
    ...(audit
      ? ([
          {
            title: '创建人',
            dataIndex: 'creator_keyword',
            hideInTable: true,
            fieldProps: { placeholder: '姓名或账号' },
          },
        ] as ProColumns<AuditCallLogItem>[])
      : []),
    ...(!audit
      ? ([
          {
            title: '密钥',
            dataIndex: 'api_key_id',
            hideInTable: true,
            renderFormItem: (_, { value, onChange }) => (
              <KeySelect value={value as number | undefined} onChange={onChange} />
            ),
          },
        ] as ProColumns<AuditCallLogItem>[])
      : []),
    {
      title: '知识库',
      dataIndex: 'dataset_id',
      hideInTable: true,
      renderFormItem: (_, { value, onChange }) => (
        <DatasetOptionSelect
          value={value as number | undefined}
          onChange={onChange as (v: never) => void}
          placeholder="全部知识库"
        />
      ),
    },
    {
      title: '结果',
      dataIndex: 'result',
      hideInTable: true,
      valueType: 'select',
      fieldProps: { options: CALL_RESULT_OPTIONS, allowClear: true, placeholder: '全部结果' },
    },
    ...(audit && showUnknownSwitch
      ? ([
          {
            title: '含无法识别密钥的调用',
            dataIndex: 'include_unknown',
            hideInTable: true,
            tooltip: '仅集团管理员 / 超级管理员可见',
            renderFormItem: (_, { value, onChange }) => (
              <Switch
                aria-label="含无法识别密钥的调用"
                checked={!!value}
                onChange={(v) => onChange?.(v)}
              />
            ),
          },
        ] as ProColumns<AuditCallLogItem>[])
      : []),
    // 列表列
    {
      title: '时间',
      dataIndex: 'called_at',
      search: false,
      width: 170,
      renderText: (v: string) => formatDateTime(v),
    },
    ...(audit
      ? ([
          {
            title: '创建人',
            search: false,
            width: 110,
            render: (_, r) => r.creator?.name ?? '-',
          },
        ] as ProColumns<AuditCallLogItem>[])
      : []),
    {
      title: '密钥',
      search: false,
      width: 190,
      render: (_, r) =>
        r.api_key ? (
          <>
            {r.api_key.name}
            <Typography.Text type="secondary">（{r.api_key.key_masked}）</Typography.Text>
          </>
        ) : (
          <Typography.Text type="secondary">无法识别密钥</Typography.Text>
        ),
    },
    {
      title: '知识库',
      search: false,
      width: 140,
      ellipsis: true,
      render: (_, r) => r.dataset?.name ?? (r.dataset ? `#${r.dataset.id}` : '-'),
    },
    {
      title: '查询文本',
      search: false,
      width: 260,
      render: (_, r) => (
        <Tooltip title={r.query ?? undefined} styles={{ root: { maxWidth: 480 } }}>
          <span>{truncateQuery(r.query)}</span>
        </Tooltip>
      ),
    },
    { title: '返回条数', dataIndex: 'result_count', search: false, width: 90 },
    {
      title: '耗时',
      dataIndex: 'latency_ms',
      search: false,
      width: 90,
      renderText: (v: number) => `${v} ms`,
    },
    {
      title: '结果',
      search: false,
      width: 160,
      render: (_, r) => <Tag color={callResultColor(r.result)}>{callResultLabel(r.result)}</Tag>,
    },
    {
      title: '调用方 IP',
      dataIndex: 'client_ip',
      search: false,
      width: 130,
      renderText: (v) => v ?? '-',
    },
  ];

  return (
    <ProTable<AuditCallLogItem, Filters>
      onRequestError={() => undefined}
      headerTitle={headerTitle}
      rowKey="id"
      actionRef={actionRef}
      columns={columns}
      params={{ fixed_key: apiKeyId }}
      scroll={{ x: audit ? 1400 : 1250 }}
      pagination={{ defaultPageSize: 20, showSizeChanger: true }}
      search={{ labelWidth: 'auto', defaultCollapsed: false }}
      form={{ initialValues: { api_key_id: apiKeyId } }}
      locale={locale ?? { emptyText: '该时间范围内没有调用记录' }}
      request={wrap(async (params: Filters & { current?: number; pageSize?: number }) => {
        const range = parseLogRange(params.time_range);
        if (range.start === null) {
          void message.warning(range.error);
          return { data: [], total: 0, success: true };
        }
        const query = {
          page: params.current ?? 1,
          page_size: params.pageSize ?? 20,
          start_time: range.start.format(),
          end_time: range.end.format(),
          api_key_id: fixedKey ? apiKeyId : params.api_key_id || undefined,
          dataset_id: params.dataset_id || undefined,
          result: params.result || undefined,
        };
        const res = audit
          ? await auditApi.callLogs({
              ...query,
              creator_keyword: params.creator_keyword?.trim() || undefined,
              include_unknown: showUnknownSwitch && params.include_unknown ? true : undefined,
            })
          : await callLogApi.list(query);
        return { data: res.items as AuditCallLogItem[], total: res.total, success: true };
      })}
    />
  );
}
