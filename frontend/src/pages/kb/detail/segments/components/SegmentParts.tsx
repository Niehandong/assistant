import { Space, Tag, Tooltip, Typography } from 'antd';
import type { SegmentItem } from '@/services/types/kb-contract';
import { indexStatusLabel } from '../logic';

export interface SegmentRowActions {
  canEdit: boolean;
  busy: string[];
  onView: (seg: SegmentItem) => void;
  onEdit: (seg: SegmentItem) => void;
  onToggle: (seg: SegmentItem, enabled: boolean) => void;
  onRemove: (seg: SegmentItem) => void;
  onAddChild: (seg: SegmentItem) => void;
  onEditChild: (seg: SegmentItem, childId: number) => void;
  onRemoveChild: (seg: SegmentItem, childId: number) => void;
}

/** 状态标签：已编辑、索引状态（失败带原因）、已禁用 */
export function SegmentTags({
  seg,
}: {
  seg: Pick<SegmentItem, 'edited' | 'index_status' | 'index_error' | 'enabled'>;
}) {
  const label = indexStatusLabel(seg.index_status);
  return (
    <Space size={4} wrap>
      {seg.edited && <Tag color="blue">已编辑</Tag>}
      {label && (
        <Tooltip title={seg.index_status === 'failed' ? seg.index_error || undefined : undefined}>
          <Tag color={seg.index_status === 'failed' ? 'error' : 'processing'}>{label}</Tag>
        </Tooltip>
      )}
      {!seg.enabled && <Tag>已禁用</Tag>}
    </Space>
  );
}

/** 内容默认 3 行，可展开 */
export function CollapsibleText({ children }: { children: string }) {
  return (
    <Typography.Paragraph
      style={{ marginBottom: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}
      ellipsis={{
        rows: 3,
        expandable: 'collapsible',
        symbol: (expanded: boolean) => (expanded ? '收起' : '展开'),
      }}
    >
      {children}
    </Typography.Paragraph>
  );
}
