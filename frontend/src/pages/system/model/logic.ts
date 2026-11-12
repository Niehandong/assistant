import type {
  ModelCreateRequest,
  ModelInUseData,
  ModelItem,
  ModelTestRequest,
  ModelTestResult,
  ModelType,
  ModelUpdateRequest,
} from '@/services/types/kb-contract';

export const MODEL_TYPE_LABEL: Record<ModelType, string> = {
  embedding: 'Embedding（向量）',
  rerank: 'Rerank（重排）',
};

/** 推荐示例仅用于引导填写，不预置为可用模型（PRD F-07 规则 9） */
export const MODEL_EXAMPLES: Record<
  ModelType,
  { model_name: string; dimension?: number; max_input_tokens?: number }
> = {
  embedding: { model_name: 'bge-m3', dimension: 1024, max_input_tokens: 8192 },
  rerank: { model_name: 'bge-reranker-v2-m3' },
};

export interface ModelFormValues {
  name: string;
  model_type: ModelType;
  base_url: string;
  model_name: string;
  api_key?: string;
  /** 编辑时勾选表示清空已保存凭据 */
  clear_api_key?: boolean;
  dimension?: number | null;
  max_input_tokens?: number;
  status: 'enabled' | 'disabled';
  is_default?: boolean;
}

/** 校验：服务地址须为 http/https */
export function isHttpUrl(value: string): boolean {
  try {
    const u = new URL(value.trim());
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch {
    return false;
  }
}

// ---------- 连通性测试状态 ----------
export type TestState =
  | { phase: 'idle' }
  | { phase: 'testing' }
  | { phase: 'success'; fingerprint: string; result: ModelTestResult }
  | { phase: 'failed'; fingerprint: string; message: string };

/** 影响连通性的字段指纹；任一变化则之前的测试结果作废 */
export function testFingerprint(
  v: Pick<ModelFormValues, 'model_type' | 'base_url' | 'model_name' | 'api_key'>,
): string {
  return [v.model_type, v.base_url?.trim() ?? '', v.model_name?.trim() ?? '', v.api_key ?? ''].join(
    '|',
  );
}

/** 把接口返回转为测试状态（success=false 取 error_message） */
export function toTestState(fingerprint: string, result: ModelTestResult): TestState {
  return result.success
    ? { phase: 'success', fingerprint, result }
    : {
        phase: 'failed',
        fingerprint,
        message: result.error_message || '连接测试未通过',
      };
}

/** 当前表单对应的测试状态：指纹不一致视为未测试 */
export function effectiveTestState(state: TestState, fingerprint: string): TestState {
  if (
    (state.phase === 'success' || state.phase === 'failed') &&
    state.fingerprint !== fingerprint
  ) {
    return { phase: 'idle' };
  }
  return state;
}

/**
 * 能否选择“启用”：本次测试通过；或编辑一个已启用且连接信息未变更的模型（服务端保存时仍会复测）。
 */
export function canChooseEnabled(
  state: TestState,
  fingerprint: string,
  editing?: ModelItem,
  savedFingerprint?: string,
): boolean {
  if (effectiveTestState(state, fingerprint).phase === 'success') return true;
  return !!editing && editing.status === 'enabled' && savedFingerprint === fingerprint;
}

// ---------- 被引用模型的只读规则 ----------
/** 被知识库引用的 Embedding 模型：地址、标识、维度只读 */
export function isConnectionLocked(editing?: ModelItem): boolean {
  return !!editing && editing.model_type === 'embedding' && editing.dataset_count > 0;
}

// ---------- 请求体构造 ----------
function trimOrUndef(s?: string): string | undefined {
  const t = s?.trim();
  return t ? t : undefined;
}

export function buildCreateRequest(v: ModelFormValues): ModelCreateRequest {
  const isEmb = v.model_type === 'embedding';
  return {
    name: v.name.trim(),
    model_type: v.model_type,
    base_url: v.base_url.trim(),
    model_name: v.model_name.trim(),
    api_key: trimOrUndef(v.api_key),
    dimension: isEmb ? (v.dimension ?? null) : null,
    max_input_tokens: v.max_input_tokens,
    status: v.status,
    is_default: v.status === 'enabled' ? !!v.is_default : false,
  };
}

/** api_key：留空 = 不修改（不传）；勾选清空 = ""（要求同时未输入新值） */
export function buildUpdateRequest(v: ModelFormValues, editing: ModelItem): ModelUpdateRequest {
  const typed = trimOrUndef(v.api_key);
  const apiKey = typed ?? (v.clear_api_key ? '' : undefined);
  const isEmb = editing.model_type === 'embedding';
  return {
    name: v.name.trim(),
    base_url: v.base_url.trim(),
    model_name: v.model_name.trim(),
    ...(apiKey !== undefined ? { api_key: apiKey } : {}),
    dimension: isEmb ? (v.dimension ?? null) : null,
    max_input_tokens: v.max_input_tokens,
    status: v.status,
    is_default: v.status === 'enabled' ? !!v.is_default : false,
    version: editing.version,
  };
}

export function buildTestRequest(v: ModelFormValues, editing?: ModelItem): ModelTestRequest {
  return {
    ...(editing ? { model_id: editing.id } : {}),
    model_type: editing?.model_type ?? v.model_type,
    base_url: trimOrUndef(v.base_url),
    model_name: trimOrUndef(v.model_name),
    api_key: trimOrUndef(v.api_key),
  };
}

// ---------- 引用名单 ----------
export function isInUseData(data: unknown): data is ModelInUseData {
  return (
    !!data &&
    typeof data === 'object' &&
    Array.isArray((data as ModelInUseData).datasets) &&
    typeof (data as ModelInUseData).total === 'number'
  );
}

/** 409301/409302 引用名单文案：最多展示 10 个，余下以“等 n 个”概括 */
export function describeInUse(data: ModelInUseData): string {
  const names = data.datasets.map((n) => `「${n}」`).join('、');
  const more = data.total > data.datasets.length ? `等共 ${data.total} 个知识库` : '';
  return `${names}${more}`;
}

/** halfvec HNSW 索引维度上限（tech-design-m2 3.10） */
export const MAX_INDEXABLE_DIMENSION = 4000;
export const HIGH_DIMENSION_HINT = '该模型维度超过 4000，无法建立向量索引，大知识库检索会变慢';

/** 以表单维度为准（测试成功会自动回填），表单为空时用测试得到的维度；超过 4000 即提示（只提示不拦截） */
export function isHighDimension(
  formDimension?: number | null,
  testDimension?: number | null,
): boolean {
  return (formDimension ?? testDimension ?? 0) > MAX_INDEXABLE_DIMENSION;
}
