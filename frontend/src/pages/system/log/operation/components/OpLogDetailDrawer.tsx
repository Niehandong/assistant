import { useQuery } from '@tanstack/react-query';
import { Button, Descriptions, Drawer, Result, Skeleton, Table, Tag } from 'antd';
import { logApi } from '@/services/iam';
import { formatDateTime } from '@/utils/format';
import { actionLabel, moduleLabel, RESULT_LABEL } from '../../dict';
import { parseSummary } from '../../summary';

export default function OpLogDetailDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['oplog-detail', id],
    queryFn: () => logApi.operationDetail(id),
  });

  let body;
  if (isLoading) body = <Skeleton active />;
  else if (isError || !data)
    body = (
      <Result
        status="error"
        title="加载失败"
        extra={<Button onClick={() => void refetch()}>重试</Button>}
      />
    );
  else {
    const parsed = parseSummary(data.summary);
    body = (
      <>
        <Descriptions column={1} bordered size="small" style={{ marginBottom: 16 }}>
          <Descriptions.Item label="时间">{formatDateTime(data.occurred_at)}</Descriptions.Item>
          <Descriptions.Item label="操作人">
            {data.operator_name ?? '-'}（{data.operator_username ?? '-'}）
          </Descriptions.Item>
          <Descriptions.Item label="所属公司">{data.company_name ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="模块">{moduleLabel(data.module)}</Descriptions.Item>
          <Descriptions.Item label="操作">
            {actionLabel(data.module, data.action)}
          </Descriptions.Item>
          <Descriptions.Item label="对象">
            {data.target_name ?? data.target_id ?? '-'}
          </Descriptions.Item>
          <Descriptions.Item label="结果">
            <Tag color={data.result === 'success' ? 'success' : 'error'}>
              {RESULT_LABEL[data.result] ?? data.result}
            </Tag>
          </Descriptions.Item>
          {data.error_message && (
            <Descriptions.Item label="失败原因">{data.error_message}</Descriptions.Item>
          )}
          <Descriptions.Item label="IP">{data.ip ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="终端">{data.user_agent ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="请求 ID">{data.request_id ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="来源服务">{data.service}</Descriptions.Item>
        </Descriptions>
        <h4>变更内容</h4>
        {parsed.kind === 'empty' && <span>无</span>}
        {parsed.kind === 'json' && (
          <pre style={{ background: '#fafafa', padding: 12, overflow: 'auto' }}>{parsed.text}</pre>
        )}
        {parsed.kind === 'kv' && (
          <Descriptions column={1} bordered size="small">
            {parsed.rows.map((r) => (
              <Descriptions.Item key={r.field} label={r.field}>
                {r.value}
              </Descriptions.Item>
            ))}
          </Descriptions>
        )}
        {parsed.kind === 'diff' && (
          <Table
            size="small"
            bordered
            pagination={false}
            rowKey="field"
            dataSource={parsed.rows}
            columns={[
              { title: '字段', dataIndex: 'field', width: 120 },
              { title: '变更前', dataIndex: 'before' },
              { title: '变更后', dataIndex: 'after' },
            ]}
          />
        )}
        {parsed.kind === 'diff' && parsed.extra && (
          <Descriptions column={1} bordered size="small" style={{ marginTop: 12 }}>
            {parsed.extra.map((r) => (
              <Descriptions.Item key={r.field} label={r.field}>
                {r.value}
              </Descriptions.Item>
            ))}
          </Descriptions>
        )}
      </>
    );
  }

  return (
    <Drawer open width={640} title="操作日志详情" onClose={onClose} destroyOnClose>
      {body}
    </Drawer>
  );
}
