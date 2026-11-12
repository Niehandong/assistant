import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Button, Card, Drawer, Result, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useState } from 'react';
import StatusTag from '@/pages/kb/detail/documents/components/StatusTag';
import { segmentCountText } from '@/pages/kb/detail/documents/logic';
import { CHUNK_MODE_LABEL } from '@/pages/kb/list/logic';
import { adminDatasetApi } from '@/services/kb';
import type { DocumentItem } from '@/services/types/kb-contract';
import { getErrorMessage } from '@/utils/error';
import { formatDateTime, formatFileSize, formatNumber } from '@/utils/format';

import AdminSegmentsView from './AdminSegmentsView';

const PAGE_SIZE = 20;

/** 管理视图：文档列表（只读，无下载/启停/删除）+ 只读分段抽屉 */
export default function AdminDocuments({ datasetId }: { datasetId: number }) {
  const [page, setPage] = useState(1);
  const [viewing, setViewing] = useState<DocumentItem | null>(null);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['kb-admin-documents', datasetId, page],
    queryFn: () => adminDatasetApi.documents(datasetId, { page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });

  const columns: ColumnsType<DocumentItem> = [
    { title: '文件名', dataIndex: 'name', ellipsis: true, width: 220 },
    { title: '类型', dataIndex: 'file_ext', width: 70, render: (v: string) => v.toUpperCase() },
    {
      title: '分段方式',
      dataIndex: 'chunk_mode',
      width: 100,
      render: (v: DocumentItem['chunk_mode']) => CHUNK_MODE_LABEL[v],
    },
    { title: '大小', dataIndex: 'file_size', width: 90, render: (v: number) => formatFileSize(v) },
    {
      title: '字符数',
      dataIndex: 'char_count',
      width: 100,
      render: (v: number) => formatNumber(v),
    },
    { title: '分段数', width: 130, render: (_, r) => segmentCountText(r) },
    {
      title: '召回次数',
      dataIndex: 'hit_count',
      width: 90,
      render: (v: number) => formatNumber(v),
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => formatDateTime(v),
    },
    { title: '状态', width: 110, render: (_, r) => <StatusTag doc={r} /> },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 80,
      render: (v: boolean) => <Tag>{v ? '已启用' : '已禁用'}</Tag>,
    },
    {
      title: '操作',
      width: 100,
      fixed: 'right',
      render: (_, r) => (
        <Button type="link" size="small" onClick={() => setViewing(r)}>
          查看分段
        </Button>
      ),
    },
  ];

  return (
    <Card size="small" title="文档列表">
      {error && !data ? (
        <Result
          status="error"
          title="加载失败"
          subTitle={getErrorMessage(error)}
          extra={
            <Button type="primary" onClick={() => void refetch()}>
              重试
            </Button>
          }
        />
      ) : (
        <Table<DocumentItem>
          size="small"
          rowKey="id"
          loading={isLoading}
          columns={columns}
          dataSource={data?.items ?? []}
          scroll={{ x: 1300 }}
          locale={{ emptyText: '该知识库还没有文档' }}
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total: data?.total ?? 0,
            showSizeChanger: false,
            onChange: setPage,
          }}
        />
      )}
      <Drawer
        title="分段内容（只读，审计查看）"
        open={!!viewing}
        width={900}
        destroyOnClose
        onClose={() => setViewing(null)}
      >
        {viewing && <AdminSegmentsView datasetId={datasetId} documentId={viewing.id} />}
      </Drawer>
    </Card>
  );
}
