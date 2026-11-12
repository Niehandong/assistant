import { isEqual } from 'lodash-es';
import { normalizeRetrievalConfig, keywordWeight } from '@/components/retrievalConfig';
import type {
  DatasetDetail,
  MyPermission,
  RecallChildChunk,
  RecallRecord,
  RetrievalConfig,
  RetrieveTestRequest,
} from '@/services/types/kb-contract';
import { KbSegmentErrorCode } from '@/services/types/kb-contract';
import { isApiError } from '@/utils/error';
import { SEARCH_METHOD_LABEL } from '../../list/logic';

export const QUERY_MAX_LENGTH = 500;
export const NO_RESULT_HINT = '未召回到相关内容，可尝试降低 Score 阈值或调整分段';

/** 问题校验：trim 后 1~500 字；返回错误文案或 null */
export function validateQuery(query: string): string | null {
  const t = query.trim();
  if (t.length === 0) return '请输入问题';
  if (t.length > QUERY_MAX_LENGTH) return `问题不能超过 ${QUERY_MAX_LENGTH} 字`;
  return null;
}

/** 测试按钮是否可用及置灰原因（无可用文档 / 向量模型停用） */
export function testAvailability(
  d: Pick<DatasetDetail, 'available_doc_count' | 'embedding_model'>,
): { enabled: boolean; reason: string | null } {
  if (d.embedding_model.status === 'disabled') {
    return { enabled: false, reason: '向量模型已停用，请联系管理员' };
  }
  if (d.available_doc_count <= 0) {
    return { enabled: false, reason: '知识库还没有可用文档，请先上传并等待处理完成' };
  }
  return { enabled: true, reason: null };
}

/** “保存为默认设置”：需 kb:dataset:update 且为所有者/可编辑 */
export function canSaveAsDefault(myPermission: MyPermission, can: (c: string) => boolean): boolean {
  return myPermission !== 'read' && can('kb:dataset:update');
}

/** 构造请求：与知识库默认设置一致时不传 retrieval_config（走默认） */
export function buildTestRequest(
  query: string,
  config: RetrievalConfig,
  defaults: RetrievalConfig,
): RetrieveTestRequest {
  const normalized = normalizeRetrievalConfig(config);
  const body: RetrieveTestRequest = { query: query.trim() };
  if (!isEqual(normalized, normalizeRetrievalConfig(defaults))) body.retrieval_config = normalized;
  return body;
}

/** 结果按得分降序（得分相同按文档、序号） */
export function sortRecords(records: RecallRecord[]): RecallRecord[] {
  return [...records].sort(
    (a, b) => b.score - a.score || a.document.id - b.document.id || a.position - b.position,
  );
}

export const formatScore = (score: number): string => score.toFixed(2);

export interface HighlightPiece {
  text: string;
  hit: boolean;
}

/**
 * 父块内容中高亮命中子块：按子块内容 indexOf 定位，重叠区间合并；
 * 找不到的子块放入 unmatched，由界面在下方单独列出。
 */
export function highlightChildren(
  content: string,
  children: RecallChildChunk[],
): { pieces: HighlightPiece[]; unmatched: RecallChildChunk[] } {
  const ranges: [number, number][] = [];
  const unmatched: RecallChildChunk[] = [];
  for (const c of children) {
    const idx = c.content ? content.indexOf(c.content) : -1;
    if (idx < 0) unmatched.push(c);
    else ranges.push([idx, idx + c.content.length]);
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const r of ranges) {
    const last = merged[merged.length - 1];
    if (last && r[0] < last[1]) last[1] = Math.max(last[1], r[1]);
    else merged.push([r[0], r[1]]);
  }
  const pieces: HighlightPiece[] = [];
  let pos = 0;
  for (const [s, e] of merged) {
    if (s > pos) pieces.push({ text: content.slice(pos, s), hit: false });
    pieces.push({ text: content.slice(s, e), hit: true });
    pos = e;
  }
  if (pos < content.length) pieces.push({ text: content.slice(pos), hit: false });
  if (pieces.length === 0) pieces.push({ text: content, hit: false });
  return { pieces, unmatched };
}

/** 召回失败文案：模型异常显示明确错误，不当成空结果 */
export function describeRecallError(err: unknown): string {
  if (isApiError(err)) {
    if (err.code === KbSegmentErrorCode.MODEL_CALL_FAILED) {
      return err.message || '模型服务调用失败，请稍后重试';
    }
    if (err.code === 409303) return '向量模型已停用，请联系管理员';
    if (err.code === KbSegmentErrorCode.NO_AVAILABLE_DOC) return '知识库没有可用文档';
    return err.message;
  }
  return err instanceof Error ? err.message : '召回测试失败';
}

/** 检索设置摘要（展示在测试区上方） */
export function summarizeConfig(c: RetrievalConfig, rerankName?: string | null): string {
  const parts = [SEARCH_METHOD_LABEL[c.search_method], `Top K ${c.top_k}`];
  parts.push(c.score_threshold_enabled ? `Score 阈值 ${c.score_threshold}` : 'Score 阈值 关');
  if (c.search_method === 'hybrid') {
    parts.push(
      c.hybrid_mode === 'rerank'
        ? `Rerank 重排${rerankName ? `（${rerankName}）` : ''}`
        : `权重 语义 ${c.vector_weight} / 关键词 ${keywordWeight(c.vector_weight)}`,
    );
  } else if (c.reranking_enable) {
    parts.push(`Rerank${rerankName ? `（${rerankName}）` : ''}`);
  }
  return parts.join(' · ');
}
