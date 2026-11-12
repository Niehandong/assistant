import { ArrowLeftOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Alert, Button, Card, Descriptions, Result, Skeleton, Space, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Access } from '@/access/Access';
import { adminDatasetApi } from '@/services/kb';
import type { AssignmentItem } from '@/services/types/kb-contract';
import { getErrorMessage, isApiError } from '@/utils/error';
import { formatDateTime } from '@/utils/format';
import {
  CHUNK_MODE_LABEL,
  CHUNK_MODE_UNSET_TEXT,
  SEARCH_METHOD_LABEL,
} from '../../../kb/list/logic';
import {
  PERMISSION_LEVEL_LABEL,
  TARGET_TYPE_LABEL,
  targetDescription,
} from '../../../kb/detail/assignments/logic';
import AdminTransferModal from '../components/AdminTransferModal';
import { orgText, ownerStatusTag, segmentText } from '../logic';
import AdminDocuments from './components/AdminDocuments';

/** 知识库管理详情（只读审计）：元信息、分配名单、文档列表、分段内容；仅提供“转移所有权” */
export default function AdminDatasetDetailPage() {
  const { id: idParam } = useParams();
  const id = Number(idParam);
  const navigate = useNavigate();
  const [transferOpen, setTransferOpen] = useState(false);

  // 进入详情页的这次请求带 audit_entry=true 记审计日志；关闭自动重取，避免重复请求
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['kb-admin-dataset', id],
    queryFn: () => adminDatasetApi.detail(id, { audit_entry: true }),
    enabled: Number.isFinite(id),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  });

  const back = (
    <Link to="/system/datasets">
      <ArrowLeftOutlined /> 返回知识库管理
    </Link>
  );

  if (isLoading) {
    return (
      <PageContainer title={false}>
        <Skeleton active paragraph={{ rows: 8 }} />
      </PageContainer>
    );
  }
  if (error || !data) {
    const notFound = isApiError(error) && (error.code === 404000 || error.status === 404);
    return (
      <PageContainer title={false}>
        <Result
          status={notFound ? '404' : 'error'}
          title={notFound ? '知识库不存在或不在您的数据范围内' : '加载失败'}
          subTitle={notFound ? undefined : getErrorMessage(error)}
          extra={
            <Space>
              {!notFound && (
                <Button type="primary" onClick={() => void refetch()}>
                  重试
                </Button>
              )}
              <Button onClick={() => navigate('/system/datasets')}>返回列表</Button>
            </Space>
          }
        />
      </PageContainer>
    );
  }

  const tag = ownerStatusTag(data.owner.status);
  const assignmentColumns: ColumnsType<AssignmentItem> = [
    { title: '对象', dataIndex: 'target_name', render: (_, r) => targetDescription(r) },
    {
      title: '类型',
      dataIndex: 'target_type',
      width: 80,
      render: (v: AssignmentItem['target_type']) => TARGET_TYPE_LABEL[v],
    },
    {
      title: '权限',
      dataIndex: 'permission',
      width: 90,
      render: (v: AssignmentItem['permission']) => PERMISSION_LEVEL_LABEL[v],
    },
    {
      title: '状态',
      width: 90,
      render: (_, r) => (r.target_valid ? <Tag color="success">有效</Tag> : <Tag>已失效</Tag>),
    },
    { title: '添加人', width: 100, render: (_, r) => r.created_by.name },
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => formatDateTime(v),
    },
  ];

  return (
    <PageContainer title={false} breadcrumbRender={false}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {back}
        <Alert type="info" showIcon message="审计查看，操作将被记录" />
        <Card
          size="small"
          title={data.name}
          extra={
            <Access code="kb:admin:transfer">
              <Button onClick={() => setTransferOpen(true)}>转移所有权</Button>
            </Access>
          }
        >
          <Descriptions column={{ xs: 1, md: 2, xl: 3 }} size="small">
            <Descriptions.Item label="所有者">
              {data.owner.name}（{data.owner.username}）{' '}
              {tag && (
                <Tag color={data.owner.status === 'deleted' ? 'error' : 'warning'}>{tag}</Tag>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="所属公司/部门">{orgText(data)}</Descriptions.Item>
            <Descriptions.Item label="分段方式">
              {data.chunk_mode ? CHUNK_MODE_LABEL[data.chunk_mode] : CHUNK_MODE_UNSET_TEXT}
            </Descriptions.Item>
            <Descriptions.Item label="文档数">{data.doc_count}</Descriptions.Item>
            <Descriptions.Item label="分段数">{segmentText(data)}</Descriptions.Item>
            <Descriptions.Item label="向量模型">{data.embedding_model.name}</Descriptions.Item>
            <Descriptions.Item label="检索方式">
              {SEARCH_METHOD_LABEL[data.retrieval_config.search_method]}
            </Descriptions.Item>
            <Descriptions.Item label="创建时间">
              {formatDateTime(data.created_at)}
            </Descriptions.Item>
            <Descriptions.Item label="最近更新">
              {formatDateTime(data.updated_at)}
            </Descriptions.Item>
            <Descriptions.Item label="描述" span={3}>
              {data.description || '-'}
            </Descriptions.Item>
          </Descriptions>
        </Card>
        <Card size="small" title="分配名单">
          <Table<AssignmentItem>
            size="small"
            rowKey="id"
            columns={assignmentColumns}
            dataSource={data.assignments}
            pagination={false}
            locale={{ emptyText: '未分配给任何对象' }}
          />
        </Card>
        <AdminDocuments datasetId={id} />
      </Space>
      {transferOpen && (
        <AdminTransferModal
          dataset={data}
          onClose={() => setTransferOpen(false)}
          onTransferred={() => navigate('/system/datasets', { replace: true })}
        />
      )}
    </PageContainer>
  );
}
