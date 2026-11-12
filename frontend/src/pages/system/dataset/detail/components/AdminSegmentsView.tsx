import { useQuery } from '@tanstack/react-query';
import { Button, Result, Skeleton } from 'antd';
import SegmentsPanel from '@/pages/kb/detail/segments/components/SegmentsPanel';
import { adminDatasetApi } from '@/services/kb';
import type { SegmentListQuery } from '@/services/types/kb-contract';
import { getErrorMessage } from '@/utils/error';

/** 管理视图只读分段：头部取文档详情（含 process_rule，不记日志），分段走 admin 接口 */
export default function AdminSegmentsView({
  datasetId,
  documentId,
}: {
  datasetId: number;
  documentId: number;
}) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['kb-admin-document', datasetId, documentId],
    queryFn: () => adminDatasetApi.documentDetail(datasetId, documentId),
  });
  if (isLoading) return <Skeleton active paragraph={{ rows: 6 }} />;
  if (error || !data) {
    return (
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
  }
  return (
    <SegmentsPanel
      scope="admin"
      datasetId={datasetId}
      doc={data}
      readonly
      canEdit={false}
      fetchSegments={(p: SegmentListQuery) => adminDatasetApi.segments(datasetId, documentId, p)}
    />
  );
}
