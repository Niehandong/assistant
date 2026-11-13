import { Collapse, Empty, List, Space, Tag, Typography } from 'antd';
import type { PreviewResult } from '@/services/types/kb-contract';

/** 分段预览（前 10 段）；父子分段可展开子块 */
export default function PreviewPanel({ result }: { result: PreviewResult }) {
  const parentChild = result.mode === 'parent_child';
  if (result.segments.length === 0) return <Empty description="没有分段结果" />;
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Typography.Text type="secondary">
        {parentChild
          ? `共 ${result.total_segments} 个父块、${result.total_child_chunks} 个子块`
          : `共 ${result.total_segments} 个分段`}
        ，文档约 {result.doc_token_count} tokens；仅展示前 {result.segments.length} 段
      </Typography.Text>
      <List
        size="small"
        bordered
        dataSource={result.segments}
        renderItem={(seg) => (
          <List.Item key={seg.position} style={{ display: 'block' }}>
            <Space style={{ marginBottom: 4 }}>
              <Tag color="blue">{parentChild ? `父块 ${seg.position}` : `#${seg.position}`}</Tag>
              <Typography.Text type="secondary">
                {seg.char_count} 字符 · {seg.token_count} tokens
              </Typography.Text>
            </Space>
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
              {seg.content}
            </Typography.Paragraph>
            {parentChild && seg.children.length > 0 && (
              <Collapse
                ghost
                size="small"
                items={[
                  {
                    key: 'c',
                    label: `子块（${seg.children.length}）`,
                    children: (
                      <List
                        size="small"
                        dataSource={seg.children}
                        renderItem={(c) => (
                          <List.Item key={c.position} style={{ display: 'block' }}>
                            <Typography.Text type="secondary">
                              子块 {c.position} · {c.char_count} 字符 · {c.token_count} tokens
                            </Typography.Text>
                            <div style={{ whiteSpace: 'pre-wrap' }}>{c.content}</div>
                          </List.Item>
                        )}
                      />
                    ),
                  },
                ]}
              />
            )}
          </List.Item>
        )}
      />
    </Space>
  );
}
