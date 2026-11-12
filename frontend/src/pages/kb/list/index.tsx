import { AppstoreOutlined, BarsOutlined, PlusOutlined } from '@ant-design/icons';
import {
  PageContainer,
  ProFormSelect,
  ProFormSwitch,
  ProFormText,
  QueryFilter,
} from '@ant-design/pro-components';
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Card,
  Col,
  Empty,
  Flex,
  Pagination,
  Result,
  Row,
  Segmented,
  Select,
  Skeleton,
} from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Access } from '@/access/Access';
import { datasetApi } from '@/services/kb';
import type { DatasetItem, DatasetSortBy } from '@/services/types/kb-contract';
import { getErrorMessage } from '@/utils/error';
import CreateDatasetModal from './components/CreateDatasetModal';
import DatasetCard from './components/DatasetCard';
import DatasetTable from './components/DatasetTable';
import DeleteDatasetModal from '../components/DeleteDatasetModal';
import {
  CHUNK_MODE_LABEL,
  CHUNK_MODE_UNSET_TEXT,
  PAGE_SIZE,
  PERMISSION_LABEL,
  SORT_OPTIONS,
  buildListQuery,
  hasActiveFilter,
  loadViewMode,
  saveViewMode,
  type ListFilters,
  type ViewMode,
} from './logic';

export default function DatasetListPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [view, setView] = useState<ViewMode>(loadViewMode);
  const [filters, setFilters] = useState<ListFilters>({});
  const [sortBy, setSortBy] = useState<DatasetSortBy>('updated_at');
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<DatasetItem | null>(null);
  const pageSize = PAGE_SIZE[view];

  const query = buildListQuery(filters, sortBy, page, pageSize);
  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['kb-datasets', query],
    queryFn: () => datasetApi.list(query),
    placeholderData: keepPreviousData,
  });

  const changeView = (v: ViewMode) => {
    setView(v);
    saveViewMode(v);
    setPage(1);
  };
  const reloadList = () => void queryClient.invalidateQueries({ queryKey: ['kb-datasets'] });

  const filtered = hasActiveFilter(filters);
  const items = data?.items ?? [];

  const createButton = (
    <Access code="kb:dataset:create">
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
        创建知识库
      </Button>
    </Access>
  );

  let body: React.ReactNode;
  if (isLoading) {
    body = <Skeleton active paragraph={{ rows: 8 }} />;
  } else if (error) {
    body = (
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
    );
  } else if (items.length === 0) {
    body = filtered ? (
      <Empty description="没有符合条件的知识库" />
    ) : (
      <Empty description="还没有可访问的知识库，创建一个开始整理你的资料吧">{createButton}</Empty>
    );
  } else if (view === 'card') {
    body = (
      <>
        <Row gutter={[16, 16]}>
          {items.map((d) => (
            <Col key={d.id} xs={24} md={12} xl={8} xxl={6}>
              <DatasetCard dataset={d} onDelete={setDeleting} />
            </Col>
          ))}
        </Row>
        <Flex justify="flex-end" style={{ marginTop: 16 }}>
          <Pagination
            current={page}
            pageSize={pageSize}
            total={data?.total ?? 0}
            showSizeChanger={false}
            showTotal={(t) => `共 ${t} 个`}
            onChange={setPage}
          />
        </Flex>
      </>
    );
  } else {
    body = (
      <DatasetTable
        data={items}
        total={data?.total ?? 0}
        page={page}
        pageSize={pageSize}
        loading={isFetching}
        onPageChange={setPage}
        onDelete={setDeleting}
      />
    );
  }

  return (
    <PageContainer title="我的知识库" extra={[<span key="c">{createButton}</span>]}>
      <Card style={{ marginBottom: 16 }} styles={{ body: { paddingBottom: 0 } }}>
        <QueryFilter<ListFilters>
          defaultCollapsed={false}
          span={6}
          labelWidth="auto"
          onFinish={async (v) => {
            setFilters(v);
            setPage(1);
          }}
          onReset={() => {
            setFilters({});
            setPage(1);
          }}
        >
          <ProFormText name="keyword" label="名称" placeholder="按名称搜索" />
          <ProFormSelect
            name="my_permission"
            label="我的权限"
            options={Object.entries(PERMISSION_LABEL).map(([value, label]) => ({ value, label }))}
          />
          <ProFormText name="owner_keyword" label="所有者" placeholder="姓名或账号" />
          <ProFormSelect
            name="chunk_mode"
            label="分段方式"
            options={[
              ...Object.entries(CHUNK_MODE_LABEL).map(([value, label]) => ({ value, label })),
              { value: 'unset', label: CHUNK_MODE_UNSET_TEXT },
            ]}
          />
          <ProFormSwitch name="only_owned" label="仅看我拥有的" />
        </QueryFilter>
      </Card>
      <Flex justify="flex-end" gap={12} style={{ marginBottom: 12 }}>
        <Select<DatasetSortBy>
          value={sortBy}
          options={SORT_OPTIONS.map((o) => ({ value: o.value, label: `按${o.label}排序` }))}
          onChange={(v) => {
            setSortBy(v);
            setPage(1);
          }}
          style={{ width: 150 }}
          aria-label="排序方式"
        />
        <Segmented<ViewMode>
          value={view}
          onChange={changeView}
          options={[
            { value: 'card', icon: <AppstoreOutlined />, label: '卡片' },
            { value: 'table', icon: <BarsOutlined />, label: '列表' },
          ]}
        />
      </Flex>
      {body}
      {creating && (
        <CreateDatasetModal
          onClose={() => setCreating(false)}
          onCreated={(d) => {
            setCreating(false);
            reloadList();
            // 跳转详情并引导上传文档
            navigate(`/kb/datasets/${d.id}/documents`, { state: { guideUpload: true } });
          }}
        />
      )}
      {deleting && (
        <DeleteDatasetModal
          dataset={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            setDeleting(null);
            reloadList();
          }}
        />
      )}
    </PageContainer>
  );
}
