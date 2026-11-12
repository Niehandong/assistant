import { Button, Card, Empty, Result, Skeleton, Table } from 'antd';
import type { RetrieveHistoryItem } from '@/services/types/kb-contract';
import { getErrorMessage } from '@/utils/error';
import { formatDateTime } from '@/utils/format';
import { SEARCH_METHOD_LABEL } from '../../../list/logic';

interface Props {
  records?: RetrieveHistoryItem[];
  loading: boolean;
  error: unknown;
  disabled: boolean;
  onRetry: () => void;
  onRetest: (record: RetrieveHistoryItem) => void;
}

/** 最近 20 条测试记录（仅本人）；一键重测 */
export default function RecallRecordTable({
  records,
  loading,
  error,
  disabled,
  onRetry,
  onRetest,
}: Props) {
  let body;
  if (loading) body = <Skeleton active paragraph={{ rows: 3 }} />;
  else if (error)
    body = (
      <Result
        status="error"
        title="记录加载失败"
        subTitle={getErrorMessage(error)}
        extra={<Button onClick={onRetry}>重试</Button>}
      />
    );
  else if (!records || records.length === 0) body = <Empty description="暂无测试记录" />;
  else
    body = (
      <Table<RetrieveHistoryItem>
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={records}
        columns={[
          { title: '问题', dataIndex: 'query', ellipsis: true },
          {
            title: '检索方式',
            dataIndex: 'search_method',
            width: 100,
            render: (v: RetrieveHistoryItem['search_method']) => SEARCH_METHOD_LABEL[v],
          },
          { title: '结果数', dataIndex: 'result_count', width: 80 },
          {
            title: '时间',
            dataIndex: 'created_at',
            width: 170,
            render: (v: string) => formatDateTime(v),
          },
          {
            title: '操作',
            width: 90,
            render: (_, r) => (
              <Button type="link" size="small" disabled={disabled} onClick={() => onRetest(r)}>
                重新测试
              </Button>
            ),
          },
        ]}
      />
    );
  return (
    <Card size="small" title="测试记录（最近 20 条，仅本人可见）">
      {body}
    </Card>
  );
}
