import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Card, Collapse, Flex, Space, Switch, Typography } from 'antd';
import type { SegmentItem } from '@/services/types/kb-contract';
import { formatNumber } from '@/utils/format';
import { CollapsibleText, SegmentTags, type SegmentRowActions } from './SegmentParts';

/** 父块：展示父块内容，展开后列出子块；启用/禁用以父块为单位 */
export default function ParentSegmentItem({
  seg,
  actions,
}: {
  seg: SegmentItem;
  actions: SegmentRowActions;
}) {
  const { canEdit, busy } = actions;
  return (
    <Card size="small" data-testid={`segment-${seg.id}`} style={{ opacity: seg.enabled ? 1 : 0.7 }}>
      <Flex justify="space-between" align="center" wrap="wrap" gap={8} style={{ marginBottom: 8 }}>
        <Space size={12} wrap>
          <strong>父块 #{seg.position}</strong>
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
      <Collapse
        ghost
        size="small"
        style={{ marginTop: 8 }}
        items={[
          {
            key: 'children',
            label: `子块（${seg.children.length}）`,
            extra: canEdit && (
              <Button
                type="link"
                size="small"
                icon={<PlusOutlined />}
                onClick={(e) => {
                  e.stopPropagation();
                  actions.onAddChild(seg);
                }}
              >
                新增子块
              </Button>
            ),
            children:
              seg.children.length === 0 ? (
                <Typography.Text type="secondary">暂无子块</Typography.Text>
              ) : (
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  {seg.children.map((c) => (
                    <Card key={c.id} size="small" type="inner" data-testid={`child-${c.id}`}>
                      <Flex justify="space-between" gap={8} wrap="wrap">
                        <Space size={8} wrap>
                          <strong>#{c.position}</strong>
                          <Typography.Text type="secondary">
                            {formatNumber(c.char_count)} 字符
                          </Typography.Text>
                          <SegmentTags seg={{ ...c, enabled: true }} />
                        </Space>
                        {canEdit && (
                          <Space size={4}>
                            <Button
                              type="link"
                              size="small"
                              onClick={() => actions.onEditChild(seg, c.id)}
                            >
                              编辑
                            </Button>
                            <Button
                              type="link"
                              size="small"
                              danger
                              onClick={() => actions.onRemoveChild(seg, c.id)}
                            >
                              删除
                            </Button>
                          </Space>
                        )}
                      </Flex>
                      <CollapsibleText>{c.content}</CollapsibleText>
                    </Card>
                  ))}
                </Space>
              ),
          },
        ]}
      />
    </Card>
  );
}
