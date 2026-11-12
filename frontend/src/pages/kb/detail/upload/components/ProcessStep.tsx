import { Alert, Button, List, Space, Typography } from 'antd';
import { useState } from 'react';
import type { DocumentProgressItem, DocumentStatus } from '@/services/types/kb-contract';
import StatusTag from '../../documents/components/StatusTag';
import { isTerminal } from '../../documents/logic';
import { useProgressPolling } from '../../documents/usePolling';

export interface SubmittedDoc {
  id: number;
  name: string;
  status: DocumentStatus;
}

interface Props {
  datasetId: number;
  docs: SubmittedDoc[];
  onBackToList: () => void;
  onAllDone: () => void;
}

/** 第三步：逐个显示处理状态（轮询 progress），用户可随时返回文档列表（处理不受影响） */
export default function ProcessStep({ datasetId, docs, onBackToList, onAllDone }: Props) {
  const [state, setState] = useState<Record<number, DocumentProgressItem>>({});
  const view = docs.map((d) => {
    const p = state[d.id];
    return {
      ...d,
      status: p?.status ?? d.status,
      progress: p?.progress ?? null,
      error_message: p?.error_message ?? null,
    };
  });
  const pending = view.filter((d) => !isTerminal(d.status)).map((d) => d.id);
  const allDone = pending.length === 0;

  useProgressPolling(
    datasetId,
    pending,
    (items) => {
      setState((prev) => {
        const next = { ...prev };
        for (const i of items) next[i.id] = i;
        return next;
      });
      if (items.every((i) => isTerminal(i.status)) && items.length === pending.length) onAllDone();
    },
    2000,
  );

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type={allDone ? 'success' : 'info'}
        showIcon
        message={allDone ? '全部文档处理完成' : '文档已提交，正在后台处理'}
        description="您可以离开此页面，处理不会受到影响。"
      />
      <List
        bordered
        size="small"
        dataSource={view}
        renderItem={(d) => (
          <List.Item key={d.id} extra={<StatusTag doc={d} />}>
            <Space direction="vertical" size={0}>
              <Typography.Text>{d.name}</Typography.Text>
              {d.status === 'failed' && d.error_message && (
                <Typography.Text type="danger" style={{ fontSize: 12 }}>
                  {d.error_message}
                </Typography.Text>
              )}
            </Space>
          </List.Item>
        )}
      />
      <Button type="primary" onClick={onBackToList}>
        返回文档列表
      </Button>
    </Space>
  );
}
