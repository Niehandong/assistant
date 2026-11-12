import { Card, Flex, Space, Tag, Tooltip, Typography } from 'antd';
import { useNavigate } from 'react-router-dom';
import DatasetIcon from '@/components/DatasetIcon';
import type { DatasetItem } from '@/services/types/kb-contract';
import { formatDateTime, formatNumber } from '@/utils/format';
import {
  PERMISSION_LABEL,
  SEARCH_METHOD_LABEL,
  buildStats,
  modelDisabledHint,
  ownerText,
} from '../logic';
import DatasetActionsMenu from './DatasetActionsMenu';

interface Props {
  dataset: DatasetItem;
  onDelete: (d: DatasetItem) => void;
}

export default function DatasetCard({ dataset: d, onDelete }: Props) {
  const navigate = useNavigate();
  const s = buildStats(d);
  const hint = modelDisabledHint(d);
  return (
    <Card
      hoverable
      size="small"
      onClick={() => navigate(`/kb/datasets/${d.id}/documents`)}
      style={{ height: '100%' }}
    >
      <Flex justify="space-between" align="flex-start" gap={8}>
        <Flex gap={8} align="center" style={{ minWidth: 0 }}>
          <DatasetIcon name={d.icon} style={{ fontSize: 24, color: '#1677ff' }} />
          <Typography.Text strong ellipsis={{ tooltip: d.name }} style={{ maxWidth: 180 }}>
            {d.name}
          </Typography.Text>
        </Flex>
        <DatasetActionsMenu dataset={d} onDelete={onDelete} />
      </Flex>
      <Typography.Paragraph
        type="secondary"
        ellipsis={{ rows: 2 }}
        style={{ margin: '8px 0', minHeight: 44 }}
      >
        {d.description || '暂无描述'}
      </Typography.Paragraph>
      <Space size={[4, 4]} wrap style={{ marginBottom: 8 }}>
        <Tag
          color={
            d.my_permission === 'owner' ? 'blue' : d.my_permission === 'edit' ? 'cyan' : 'default'
          }
        >
          {PERMISSION_LABEL[d.my_permission]}
        </Tag>
        <Tag color={s.chunkModeUnset ? undefined : 'geekblue'}>{s.chunkModeText}</Tag>
        <Tag>高质量</Tag>
        <Tag>{SEARCH_METHOD_LABEL[d.search_method]}</Tag>
        {s.badges.map((b) => (
          <Tag key={b.kind} color={b.kind === 'failed' ? 'error' : 'processing'}>
            {b.text}
          </Tag>
        ))}
        {hint && <Tag color="warning">{hint}</Tag>}
      </Space>
      <Flex gap={16} wrap style={{ fontSize: 13 }}>
        <span>文档 {s.docText}</span>
        <span>
          {s.segmentLabel} {s.segmentText}
        </span>
        <span>字符 {formatNumber(d.char_count)}</span>
      </Flex>
      <Flex justify="space-between" style={{ marginTop: 8, fontSize: 12 }}>
        <Typography.Text type="secondary" ellipsis style={{ maxWidth: 110 }}>
          所有者：{ownerText(d)}
        </Typography.Text>
        <Tooltip title="最近更新时间">
          <Typography.Text type="secondary">{formatDateTime(d.updated_at)}</Typography.Text>
        </Tooltip>
      </Flex>
    </Card>
  );
}
