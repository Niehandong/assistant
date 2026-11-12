import { ProTable, type ProColumns } from '@ant-design/pro-components';
import { Space, Tag, Typography } from 'antd';
import { Link } from 'react-router-dom';
import DatasetIcon from '@/components/DatasetIcon';
import type { DatasetItem } from '@/services/types/kb-contract';
import { formatDateTime, formatNumber } from '@/utils/format';
import {
  PERMISSION_LABEL,
  SEARCH_METHOD_LABEL,
  buildStats,
  modelDisabledHint,
  ownerText,
} from '../logic';
import DatasetActionsMenu from './DatasetActionsMenu';

interface Props {
  data: DatasetItem[];
  total: number;
  page: number;
  pageSize: number;
  loading: boolean;
  onPageChange: (page: number) => void;
  onDelete: (d: DatasetItem) => void;
}

/** 列表视图：纯展示的 ProTable，筛选/排序/分页由页面统一控制 */
export default function DatasetTable({
  data,
  total,
  page,
  pageSize,
  loading,
  onPageChange,
  onDelete,
}: Props) {
  const columns: ProColumns<DatasetItem>[] = [
    {
      title: '名称',
      dataIndex: 'name',
      width: 220,
      render: (_, r) => (
        <Space>
          <DatasetIcon name={r.icon} style={{ color: '#1677ff' }} />
          <Link to={`/kb/datasets/${r.id}/documents`}>{r.name}</Link>
          {modelDisabledHint(r) && <Tag color="warning">{modelDisabledHint(r)}</Tag>}
        </Space>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      width: 200,
      render: (_, r) => (
        <Typography.Paragraph
          type="secondary"
          ellipsis={{ rows: 2, tooltip: r.description ?? undefined }}
          style={{ margin: 0 }}
        >
          {r.description || '-'}
        </Typography.Paragraph>
      ),
    },
    {
      title: '文档数',
      dataIndex: 'doc_count',
      width: 130,
      render: (_, r) => {
        const s = buildStats(r);
        return (
          <Space size={4} wrap>
            <span>{s.docText}</span>
            {s.badges.map((b) => (
              <Tag key={b.kind} color={b.kind === 'failed' ? 'error' : 'processing'}>
                {b.text}
              </Tag>
            ))}
          </Space>
        );
      },
    },
    {
      title: '分段数',
      dataIndex: 'segment_count',
      width: 150,
      render: (_, r) => buildStats(r).segmentText,
    },
    {
      title: '字符数',
      dataIndex: 'char_count',
      width: 100,
      renderText: (v: number) => formatNumber(v),
    },
    {
      title: '分段方式',
      dataIndex: 'chunk_mode',
      width: 120,
      render: (_, r) => buildStats(r).chunkModeText,
    },
    { title: '索引方式', dataIndex: 'indexing_technique', width: 90, renderText: () => '高质量' },
    {
      title: '检索方式',
      dataIndex: 'search_method',
      width: 100,
      renderText: (v: DatasetItem['search_method']) => SEARCH_METHOD_LABEL[v],
    },
    { title: '所有者', dataIndex: 'owner', width: 120, renderText: (_, r) => ownerText(r) },
    {
      title: '我的权限',
      dataIndex: 'my_permission',
      width: 90,
      renderText: (v: DatasetItem['my_permission']) => PERMISSION_LABEL[v],
    },
    {
      title: '最近更新',
      dataIndex: 'updated_at',
      width: 170,
      renderText: (v: string) => formatDateTime(v),
    },
    {
      title: '操作',
      valueType: 'option',
      fixed: 'right',
      width: 70,
      render: (_, r) => <DatasetActionsMenu dataset={r} onDelete={onDelete} />,
    },
  ];
  return (
    <ProTable<DatasetItem>
      rowKey="id"
      columns={columns}
      dataSource={data}
      loading={loading}
      search={false}
      options={false}
      toolBarRender={false}
      scroll={{ x: 1500 }}
      pagination={{
        current: page,
        pageSize,
        total,
        showSizeChanger: false,
        onChange: onPageChange,
      }}
    />
  );
}
