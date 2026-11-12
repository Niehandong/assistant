import { DeleteOutlined, UploadOutlined } from '@ant-design/icons';
import {
  ProFormSelect,
  ProFormText,
  ProTable,
  QueryFilter,
  type ProColumns,
} from '@ant-design/pro-components';
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, App, Button, Card, Flex, Space, Switch, Typography } from 'antd';
import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Access } from '@/access/Access';
import { usePermission } from '@/access/usePermission';
import { documentApi } from '@/services/kb';
import type { DocumentItem, DocumentProgressItem, PageResult } from '@/services/types/kb-contract';
import { getErrorMessage } from '@/utils/error';
import { formatDateTime, formatFileSize, formatNumber } from '@/utils/format';
import { notifyError } from '@/utils/notify';
import { CHUNK_MODE_LABEL } from '../../list/logic';
import { useDataset, useRefreshDataset } from '../useDataset';
import ReprocessModal from './components/ReprocessModal';
import StatusTag from './components/StatusTag';
import {
  STATUS_FILTER_OPTIONS,
  buildDocQuery,
  canReprocess,
  canRetry,
  mergeProgress,
  pendingIds,
  saveBlob,
  segmentCountText,
  toDocSort,
  type DocFilters,
  type DocSort,
  DEFAULT_DOC_SORT,
} from './logic';
import { useProgressPolling } from './usePolling';

const PAGE_SIZE = 20;

export default function DocumentsPage() {
  const dataset = useDataset();
  const navigate = useNavigate();
  const location = useLocation();
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const can = usePermission();
  const refreshDataset = useRefreshDataset(dataset.id);

  const [filters, setFilters] = useState<DocFilters>({});
  const [sort, setSort] = useState<DocSort>(DEFAULT_DOC_SORT);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<number[]>([]);
  const [reprocessing, setReprocessing] = useState<DocumentItem | null>(null);
  const [guide, setGuide] = useState(
    () => (location.state as { guideUpload?: boolean } | null)?.guideUpload === true,
  );

  const canEditLevel = dataset.my_permission !== 'read';
  const modelDisabled = dataset.embedding_model.status === 'disabled';
  const canUpload = canEditLevel && can('kb:document:upload') && !modelDisabled;
  const canUpdate = canEditLevel && can('kb:document:update');
  const canDelete = canEditLevel && can('kb:document:delete');
  const canDownload = can('kb:document:download');
  const uploadPath = `/kb/datasets/${dataset.id}/documents/upload`;

  const query = buildDocQuery(filters, sort, page, PAGE_SIZE);
  const listKey = ['kb-documents', dataset.id, query];
  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: listKey,
    queryFn: () => documentApi.list(dataset.id, query),
    placeholderData: keepPreviousData,
  });
  const rows = data?.items ?? [];

  // 存在非终态文档时每 3 秒局部刷新；进入终态后刷新统计并停止
  useProgressPolling(dataset.id, pendingIds(rows), (items: DocumentProgressItem[]) => {
    const becameTerminal = items.some(
      (p) =>
        (p.status === 'available' || p.status === 'failed') &&
        rows.find((r) => r.id === p.id && r.status !== p.status),
    );
    qc.setQueryData<PageResult<DocumentItem>>(listKey, (old) =>
      old ? { ...old, items: mergeProgress(old.items, items) } : old,
    );
    if (becameTerminal) void refreshDataset();
  });

  const reload = () => {
    void qc.invalidateQueries({ queryKey: ['kb-documents', dataset.id] });
    void refreshDataset();
  };

  const run = async (fn: () => Promise<unknown>, okText: string) => {
    try {
      await fn();
      void message.success(okText);
      setSelected([]);
      reload();
    } catch (err) {
      notifyError(err);
      reload();
    }
  };

  const toggleEnabled = (ids: number[], enabled: boolean) =>
    run(
      () => documentApi.setEnabled(dataset.id, { document_ids: ids, enabled }),
      enabled ? '已启用' : '已禁用',
    );

  const confirmDelete = (ids: number[], title: string) =>
    modal.confirm({
      title,
      content: '文档及其分段将一并删除，处理中的文档会取消处理，删除后不可恢复。',
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: () => run(() => documentApi.batchDelete(dataset.id, { document_ids: ids }), '已删除'),
    });

  const download = async (doc: DocumentItem) => {
    try {
      const { blob, filename } = await documentApi.download(dataset.id, doc.id);
      saveBlob(blob, filename ?? doc.name);
    } catch (err) {
      notifyError(err);
    }
  };

  const columns: ProColumns<DocumentItem>[] = [
    {
      title: '文件名',
      dataIndex: 'name',
      width: 240,
      ellipsis: true,
      render: (_, r) => (
        <Link to={`/kb/datasets/${dataset.id}/documents/${r.id}/segments`}>{r.name}</Link>
      ),
    },
    {
      title: '类型',
      dataIndex: 'file_ext',
      width: 70,
      renderText: (v: string) => v.toUpperCase(),
    },
    {
      title: '分段方式',
      dataIndex: 'chunk_mode',
      width: 100,
      renderText: (v: DocumentItem['chunk_mode']) => CHUNK_MODE_LABEL[v],
    },
    {
      title: '大小',
      dataIndex: 'file_size',
      width: 90,
      renderText: (v: number) => formatFileSize(v),
    },
    {
      title: '字符数',
      dataIndex: 'char_count',
      width: 100,
      sorter: true,
      sortOrder:
        sort.sort_by === 'char_count' ? (sort.sort_order === 'asc' ? 'ascend' : 'descend') : null,
      renderText: (v: number) => formatNumber(v),
    },
    {
      title: dataset.chunk_mode === 'parent_child' ? '分段数（父块/子块）' : '分段数',
      dataIndex: 'segment_count',
      width: 150,
      render: (_, r) => segmentCountText(r),
    },
    {
      title: '召回次数',
      dataIndex: 'hit_count',
      width: 100,
      sorter: true,
      sortOrder:
        sort.sort_by === 'hit_count' ? (sort.sort_order === 'asc' ? 'ascend' : 'descend') : null,
      renderText: (v: number) => formatNumber(v),
    },
    {
      title: '上传人',
      dataIndex: 'uploaded_by',
      width: 100,
      renderText: (_, r) => r.uploaded_by.name,
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      width: 170,
      sorter: true,
      sortOrder:
        sort.sort_by === 'created_at' ? (sort.sort_order === 'asc' ? 'ascend' : 'descend') : null,
      renderText: (v: string) => formatDateTime(v),
    },
    {
      title: '处理状态',
      dataIndex: 'status',
      width: 140,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <StatusTag doc={r} />
          {r.status === 'failed' && r.error_message && (
            <Typography.Text type="danger" style={{ fontSize: 12 }}>
              {r.error_message}
            </Typography.Text>
          )}
        </Space>
      ),
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 70,
      render: (_, r) => (
        <Switch
          size="small"
          aria-label={`启用 ${r.name}`}
          checked={r.enabled}
          disabled={!canUpdate}
          onChange={(v) => void toggleEnabled([r.id], v)}
        />
      ),
    },
    {
      title: '操作',
      valueType: 'option',
      fixed: 'right',
      width: 260,
      render: (_, r) => (
        <Space size={0} wrap>
          <Button
            type="link"
            size="small"
            onClick={() => navigate(`/kb/datasets/${dataset.id}/documents/${r.id}/segments`)}
          >
            查看分段
          </Button>
          {canUpdate && canRetry(r) && (
            <Button
              type="link"
              size="small"
              onClick={() => void run(() => documentApi.retry(dataset.id, r.id), '已提交重试')}
            >
              重试
            </Button>
          )}
          {canUpdate && canReprocess(r) && (
            <Button type="link" size="small" onClick={() => setReprocessing(r)}>
              重新分段
            </Button>
          )}
          {canDownload && (
            <Button type="link" size="small" onClick={() => void download(r)}>
              下载
            </Button>
          )}
          {canDelete && (
            <Button
              type="link"
              size="small"
              danger
              onClick={() => confirmDelete([r.id], `确认删除文档「${r.name}」？`)}
            >
              删除
            </Button>
          )}
        </Space>
      ),
    },
  ];

  const hasFilter = !!(filters.keyword?.trim() || filters.status || filters.enabled);

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {guide && (
        <Alert
          type="success"
          showIcon
          closable
          onClose={() => {
            setGuide(false);
            navigate(location.pathname, { replace: true, state: null });
          }}
          message="知识库创建成功"
          description={
            canUpload
              ? '接下来上传文档，系统会自动解析、分段并建立索引。'
              : '暂无上传文档的权限或向量模型不可用，可联系管理员处理。'
          }
          action={
            canUpload ? (
              <Button type="primary" onClick={() => navigate(uploadPath)}>
                上传文档
              </Button>
            ) : undefined
          }
        />
      )}
      <Card size="small" styles={{ body: { paddingBottom: 0 } }}>
        <QueryFilter<{
          keyword?: string;
          status?: DocFilters['status'];
          enabled?: DocFilters['enabled'];
        }>
          defaultCollapsed={false}
          span={8}
          labelWidth="auto"
          onFinish={async (v) => {
            setFilters(v);
            setPage(1);
            setSelected([]);
          }}
          onReset={() => {
            setFilters({});
            setPage(1);
          }}
        >
          <ProFormText name="keyword" label="文件名" placeholder="按文件名搜索" />
          <ProFormSelect name="status" label="处理状态" options={STATUS_FILTER_OPTIONS} />
          <ProFormSelect
            name="enabled"
            label="启用状态"
            options={[
              { value: 'true', label: '已启用' },
              { value: 'false', label: '已禁用' },
            ]}
          />
        </QueryFilter>
      </Card>
      <Card
        size="small"
        title="文档"
        extra={
          canUpload && (
            <Access code="kb:document:upload">
              <Button type="primary" icon={<UploadOutlined />} onClick={() => navigate(uploadPath)}>
                上传文档
              </Button>
            </Access>
          )
        }
      >
        {error && !data ? (
          <Flex vertical align="center" gap={8} style={{ padding: 32 }}>
            <Typography.Text strong>加载失败</Typography.Text>
            <Typography.Text type="secondary">{getErrorMessage(error)}</Typography.Text>
            <Button type="primary" onClick={() => void refetch()}>
              重试
            </Button>
          </Flex>
        ) : (
          <ProTable<DocumentItem>
            rowKey="id"
            columns={columns}
            dataSource={rows}
            loading={isLoading || isFetching}
            search={false}
            options={false}
            toolBarRender={false}
            scroll={{ x: 1650 }}
            locale={{
              emptyText: hasFilter
                ? '没有符合条件的文档'
                : canUpload
                  ? '还没有文档，点击右上角“上传文档”开始'
                  : '还没有文档',
            }}
            rowSelection={
              canUpdate || canDelete
                ? { selectedRowKeys: selected, onChange: (keys) => setSelected(keys as number[]) }
                : false
            }
            tableAlertRender={({ selectedRowKeys }) => `已选择 ${selectedRowKeys.length} 项`}
            tableAlertOptionRender={() => (
              <Space>
                {canUpdate && (
                  <>
                    <Button size="small" onClick={() => void toggleEnabled(selected, true)}>
                      批量启用
                    </Button>
                    <Button size="small" onClick={() => void toggleEnabled(selected, false)}>
                      批量禁用
                    </Button>
                  </>
                )}
                {canDelete && (
                  <Button
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() =>
                      confirmDelete(selected, `确认删除选中的 ${selected.length} 个文档？`)
                    }
                  >
                    批量删除
                  </Button>
                )}
              </Space>
            )}
            onChange={(_p, _f, sorter) => {
              const s = Array.isArray(sorter) ? sorter[0] : sorter;
              setSort(toDocSort(s?.field as string | undefined, s?.order));
              setPage(1);
            }}
            pagination={{
              current: page,
              pageSize: PAGE_SIZE,
              total: data?.total ?? 0,
              showSizeChanger: false,
              onChange: setPage,
            }}
          />
        )}
      </Card>
      {reprocessing && (
        <ReprocessModal
          dataset={dataset}
          doc={reprocessing}
          onClose={() => setReprocessing(null)}
          onSuccess={() => {
            setReprocessing(null);
            reload();
          }}
        />
      )}
    </Space>
  );
}
