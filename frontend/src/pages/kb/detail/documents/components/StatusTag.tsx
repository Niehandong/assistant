import { CheckCircleFilled, CloseCircleFilled, LoadingOutlined } from '@ant-design/icons';
import { Tag, Tooltip } from 'antd';
import type { DocumentItem } from '@/services/types/kb-contract';
import { statusText } from '../logic';

/** 文档处理状态标签：处理中带进度，失败带原因 */
export default function StatusTag({
  doc,
}: {
  doc: Pick<DocumentItem, 'status' | 'progress' | 'error_message'>;
}) {
  const text = statusText(doc);
  if (doc.status === 'available') {
    return (
      <Tag icon={<CheckCircleFilled />} color="success">
        {text}
      </Tag>
    );
  }
  if (doc.status === 'failed') {
    return (
      <Tooltip title={doc.error_message || '处理失败'}>
        <Tag icon={<CloseCircleFilled />} color="error">
          {text}
        </Tag>
      </Tooltip>
    );
  }
  return (
    <Tag icon={<LoadingOutlined />} color="processing">
      {text}
    </Tag>
  );
}
