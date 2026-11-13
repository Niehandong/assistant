import { DeleteOutlined, EditOutlined } from '@ant-design/icons';
import { Button, Card, Flex, Space, Switch, Tag, Typography } from 'antd';
import type { ReactNode } from 'react';
import type { SegmentItem } from '@/services/types/kb-contract';
import { formatNumber } from '@/utils/format';
import ParentSegmentItem from './ParentSegmentItem';
import { CollapsibleText, SegmentTags, type SegmentRowActions } from './SegmentParts';

function GeneralItem({ seg, actions }: { seg: SegmentItem; actions: SegmentRowActions }) {
  const { canEdit, busy } = actions;
  return (
    <Card size="small" data-testid={`segment-${seg.id}`} style={{ opacity: seg.enabled ? 1 : 0.7 }}>
      <Flex justify="space-between" align="center" wrap="wrap" gap={8} style={{ marginBottom: 8 }}>
        <Space size={12} wrap>
          <strong>#{seg.position}</strong>
          <Typography.Text type="secondary">{formatNumber(seg.char_count)} 字符</Typography.Text>
          <Typography.Text type="secondary">召回 {formatNumber(seg.hit_count)} 次</Typography.Text>
          <SegmentTags seg={seg} />
        </Space>
        <Space size={4}>
          <Switch
            size="small"
            aria-label={`启用分段 ${seg.position}`}
            checked={seg.enabled}
            disabled={!canEdit}
            loading={busy.includes(`s${seg.id}`)}
            onChange={(v) => actions.onToggle(seg, v)}
          />
          <Button type="link" size="small" onClick={() => actions.onView(seg)}>
            详情
          </Button>
          {canEdit && (
            <>
              <Button
                type="link"
                size="small"
                icon={<EditOutlined />}
                onClick={() => actions.onEdit(seg)}
              >
                编辑
              </Button>
              <Button
                type="link"
                size="small"
                danger
                icon={<DeleteOutlined />}
                onClick={() => actions.onRemove(seg)}
              >
                删除
              </Button>
            </>
          )}
        </Space>
      </Flex>
      <CollapsibleText>{seg.content}</CollapsibleText>
      {seg.keywords.length > 0 && (
        <Space size={[4, 4]} wrap style={{ marginTop: 8 }}>
          {seg.keywords.map((k) => (
            <Tag key={k}>{k}</Tag>
          ))}
        </Space>
      )}
    </Card>
  );
}

interface Props {
  items: SegmentItem[];
  actions: SegmentRowActions;
  empty: ReactNode;
}

/** 分段列表：按类型分发为通用分段或父块（含子块） */
export default function SegmentList({ items, actions, empty }: Props) {
  if (items.length === 0) return <>{empty}</>;
  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      {items.map((seg) =>
        seg.segment_type === 'parent' ? (
          <ParentSegmentItem key={seg.id} seg={seg} actions={actions} />
        ) : (
          <GeneralItem key={seg.id} seg={seg} actions={actions} />
        ),
      )}
    </Space>
  );
}
