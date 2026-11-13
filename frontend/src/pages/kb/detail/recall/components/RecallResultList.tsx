import { Alert, Card, Drawer, Empty, Flex, Space, Tag, Typography } from 'antd';
import { useState } from 'react';
import type { RecallRecord, RetrievalResult } from '@/services/types/kb-contract';
import { NO_RESULT_HINT, formatScore, highlightChildren, sortRecords } from '../logic';

/** 得分条：藤黄填充表示命中强度（得分按 0~1 截断），数值用等宽数字 */
function ScoreBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(1, score)) * 100;
  return (
    <span
      data-testid="score-bar"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        fontVariantNumeric: 'tabular-nums',
      }}
    >
      <span>得分 {formatScore(score)}</span>
      <span
        aria-hidden
        style={{ width: 56, height: 6, borderRadius: 3, background: '#E2E7E4', overflow: 'hidden' }}
      >
        <span
          style={{ display: 'block', width: `${pct}%`, height: '100%', background: '#F2C14E' }}
        />
      </span>
    </span>
  );
}

function Highlighted({ record }: { record: RecallRecord }) {
  const { pieces, unmatched } = highlightChildren(record.content, record.child_chunks);
  return (
    <>
      <Typography.Paragraph
        style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', marginBottom: 0 }}
      >
        {pieces.map((p, i) =>
          p.hit ? (
            <mark key={i} data-testid="hit-mark">
              {p.text}
            </mark>
          ) : (
            <span key={i}>{p.text}</span>
          ),
        )}
      </Typography.Paragraph>
      {unmatched.length > 0 && (
        <div style={{ marginTop: 8 }} data-testid="unmatched-children">
          <Typography.Text type="secondary">未在父块中定位到的命中子块：</Typography.Text>
          {unmatched.map((c) => (
            <div key={c.id}>
              <Tag>子块 #{c.position}</Tag>
              <mark>{c.content}</mark>
              <Typography.Text type="secondary"> 得分 {formatScore(c.score)}</Typography.Text>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function Content({ record, full }: { record: RecallRecord; full: boolean }) {
  if (record.segment_type === 'parent') return <Highlighted record={record} />;
  return (
    <Typography.Paragraph
      style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', marginBottom: 0 }}
      ellipsis={full ? false : { rows: 4 }}
    >
      {record.content}
    </Typography.Paragraph>
  );
}

/** 召回结果列表：按得分降序，点击看详情；父子结果显示父块并高亮命中子块 */
export default function RecallResultList({ result }: { result: RetrievalResult }) {
  const [detail, setDetail] = useState<RecallRecord | null>(null);
  const records = sortRecords(result.records);

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {result.rerank_skipped && (
        <Alert
          type="warning"
          showIcon
          message={`未执行 Rerank，已按原得分返回${result.rerank_skipped_reason ? `：${result.rerank_skipped_reason}` : ''}`}
        />
      )}
      {records.length === 0 ? (
        <Empty description={NO_RESULT_HINT} />
      ) : (
        records.map((r, idx) => (
          <Card
            key={r.segment_id}
            size="small"
            hoverable
            data-testid="recall-record"
            onClick={() => setDetail(r)}
            title={
              <Space size={8} wrap>
                <span>#{idx + 1}</span>
                <ScoreBar score={r.score} />
                <Typography.Text type="secondary" style={{ fontWeight: 'normal' }}>
                  {r.document.name} · 分段 #{r.position}
                  {r.segment_type === 'parent' ? '（父块）' : ''}
                </Typography.Text>
              </Space>
            }
          >
            <Content record={r} full={false} />
          </Card>
        ))
      )}
      <Drawer
        title={detail ? `${detail.document.name} · 分段 #${detail.position}` : ''}
        open={!!detail}
        width={560}
        onClose={() => setDetail(null)}
      >
        {detail && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Flex gap={8} wrap="wrap">
              <ScoreBar score={detail.score} />
              {detail.keywords.map((k) => (
                <Tag key={k}>{k}</Tag>
              ))}
            </Flex>
            <Content record={detail} full />
            {detail.child_chunks.length > 0 && (
              <div>
                <Typography.Text strong>命中子块</Typography.Text>
                {detail.child_chunks.map((c) => (
                  <div key={c.id}>
                    #{c.position} 得分 {formatScore(c.score)}
                  </div>
                ))}
              </div>
            )}
          </Space>
        )}
      </Drawer>
    </Space>
  );
}
