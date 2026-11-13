import { useQuery } from '@tanstack/react-query';
import { Alert, Button, Empty, Modal, Result, Skeleton } from 'antd';
import { apiKeyApi } from '@/services/open';

interface Props {
  keyId: number;
  keyName: string;
  onClose: () => void;
}

/** 当前真正可检索的知识库名单（创建人可访问 ∩ 指定集合，5.1.8） */
export default function AccessibleDatasetsModal({ keyId, keyName, onClose }: Props) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['open-key-accessible', keyId],
    queryFn: () => apiKeyApi.accessibleDatasets(keyId),
    gcTime: 0,
  });

  let body;
  if (isLoading) body = <Skeleton active paragraph={{ rows: 4 }} />;
  else if (error)
    body = (
      <Result
        status="error"
        title="加载失败"
        subTitle={error.message}
        extra={<Button onClick={() => void refetch()}>重试</Button>}
      />
    );
  else if (!data || data.length === 0) body = <Empty description="当前没有可检索的知识库" />;
  else
    body = (
      <ul style={{ margin: 0, paddingLeft: 20, maxHeight: 360, overflow: 'auto' }}>
        {data.map((d) => (
          <li key={d.id}>
            {d.name}
            <span style={{ color: '#999' }}>（ID：{d.id}）</span>
          </li>
        ))}
      </ul>
    );

  return (
    <Modal open title={`「${keyName}」当前可检索的知识库`} footer={null} onCancel={onClose}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="可检索范围实时跟随创建人当前的知识库访问权限。"
      />
      {body}
    </Modal>
  );
}
