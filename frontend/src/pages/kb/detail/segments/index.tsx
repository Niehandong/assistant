import { ArrowLeftOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { Button, Result, Skeleton, Space } from 'antd';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { usePermission } from '@/access/usePermission';
import { documentApi, segmentApi } from '@/services/kb';
import type { SegmentListQuery } from '@/services/types/kb-contract';
import { isApiError } from '@/utils/error';
import { useDataset } from '../useDataset';
import SegmentsPanel from './components/SegmentsPanel';
import { resolveEditAccess } from './logic';

/** 文档分段页（FE-13）：路由 /kb/datasets/:id/documents/:documentId/segments */
export default function SegmentsPage() {
  const dataset = useDataset();
  const { documentId: docParam } = useParams();
  const documentId = Number(docParam);
  const navigate = useNavigate();
  const can = usePermission();

  const {
    data: doc,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['kb-document', dataset.id, documentId],
    queryFn: () => documentApi.detail(dataset.id, documentId),
    enabled: Number.isFinite(documentId),
    // 处理中的文档状态会变化，终态后停止
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s && s !== 'available' && s !== 'failed' ? 3000 : false;
    },
  });

  const back = (
    <Link to={`/kb/datasets/${dataset.id}/documents`}>
      <ArrowLeftOutlined /> 返回文档列表
    </Link>
  );

  if (isLoading) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (error || !doc) {
    const notFound = isApiError(error) && (error.code === 404000 || error.status === 404);
    return (
      <Result
        status={notFound ? '404' : 'error'}
        title={notFound ? '文档不存在' : '加载失败'}
        subTitle={notFound ? undefined : (error as Error | null)?.message}
        extra={
          notFound ? (
            <Button type="primary" onClick={() => navigate(`/kb/datasets/${dataset.id}/documents`)}>
              返回文档列表
            </Button>
          ) : (
            <Button type="primary" onClick={() => void refetch()}>
              重试
            </Button>
          )
        }
      />
    );
  }

  const access = resolveEditAccess({
    readonly: false,
    myPermission: dataset.my_permission,
    hasUpdatePerm: can('kb:segment:update'),
    docStatus: doc.status,
  });
  const fetchSegments = (params: SegmentListQuery) => segmentApi.list(dataset.id, doc.id, params);

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {back}
      <SegmentsPanel
        scope="normal"
        datasetId={dataset.id}
        doc={doc}
        readonly={false}
        canEdit={access.canEdit}
        disabledReason={access.reason}
        fetchSegments={fetchSegments}
      />
    </Space>
  );
}
