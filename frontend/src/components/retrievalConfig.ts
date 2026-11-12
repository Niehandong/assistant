import type { ModelOption, RetrievalConfig } from '@/services/types/kb-contract';

/** 检索设置默认值（tech-design-m2 5.2.6） */
export const DEFAULT_RETRIEVAL_CONFIG: RetrievalConfig = {
  search_method: 'vector',
  top_k: 3,
  score_threshold_enabled: false,
  score_threshold: 0.5,
  reranking_enable: false,
  reranking_model_id: null,
  hybrid_mode: 'weighted',
  vector_weight: 0.7,
};

export type RetrievalErrors = Partial<Record<keyof RetrievalConfig, string>>;

const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v);

/** 关键词权重 = 1 - 语义权重（保留一位小数，避免 0.30000000000000004） */
export function keywordWeight(vectorWeight: number): number {
  return Math.round((1 - vectorWeight) * 10) / 10;
}

/** 是否需要 Rerank 模型：向量/全文开启 Rerank，或混合模式选择 Rerank */
export function needsRerankModel(c: RetrievalConfig): boolean {
  return c.search_method === 'hybrid' ? c.hybrid_mode === 'rerank' : c.reranking_enable;
}

/** 校验（AC-48）：返回字段 -> 错误文案；空对象表示通过 */
export function validateRetrievalConfig(
  c: RetrievalConfig,
  rerankModels: Pick<ModelOption, 'id'>[],
): RetrievalErrors {
  const errors: RetrievalErrors = {};
  if (!isInt(c.top_k) || c.top_k < 1 || c.top_k > 20) {
    errors.top_k = 'Top K 须为 1~20 的整数';
  }
  if (c.score_threshold_enabled) {
    const t = c.score_threshold;
    if (typeof t !== 'number' || Number.isNaN(t) || t < 0 || t > 1) {
      errors.score_threshold = 'Score 阈值须在 0~1 之间';
    }
  }
  if (c.search_method === 'hybrid' && c.hybrid_mode === 'weighted') {
    const w = c.vector_weight;
    if (typeof w !== 'number' || w < 0 || w > 1) {
      errors.vector_weight = '语义权重须在 0~1 之间';
    }
  }
  if (needsRerankModel(c)) {
    if (c.reranking_model_id == null) {
      errors.reranking_model_id = '请选择已启用的 Rerank 模型';
    } else if (!rerankModels.some((m) => m.id === c.reranking_model_id)) {
      errors.reranking_model_id = '所选 Rerank 模型已不可用，请重新选择';
    }
  }
  return errors;
}

/** 提交前整理：不适用的字段回到默认，避免残留；阈值保留两位小数 */
export function normalizeRetrievalConfig(c: RetrievalConfig): RetrievalConfig {
  const hybrid = c.search_method === 'hybrid';
  const rerank = needsRerankModel(c);
  return {
    search_method: c.search_method,
    top_k: c.top_k,
    score_threshold_enabled: c.score_threshold_enabled,
    score_threshold: Math.round(c.score_threshold * 100) / 100,
    reranking_enable: hybrid ? false : c.reranking_enable,
    reranking_model_id: rerank ? c.reranking_model_id : null,
    hybrid_mode: hybrid ? c.hybrid_mode : 'weighted',
    vector_weight: hybrid
      ? Math.round(c.vector_weight * 10) / 10
      : DEFAULT_RETRIEVAL_CONFIG.vector_weight,
  };
}

/** 切换检索方式：Rerank 开关仅对向量/全文有效，切到混合时关闭 */
export function changeSearchMethod(
  c: RetrievalConfig,
  method: RetrievalConfig['search_method'],
): RetrievalConfig {
  return {
    ...c,
    search_method: method,
    reranking_enable: method === 'hybrid' ? false : c.reranking_enable,
  };
}
