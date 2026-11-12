import type { OpenErrorRow } from '@/services/types/open-contract';

/** 调用地址（5.4）：以当前站点 origin 为准 */
export function buildEndpoint(origin: string, datasetId: number | string = '{dataset_id}'): string {
  return `${origin}/api/v1/open/datasets/${datasetId}/retrieve`;
}

export interface ParamRow {
  name: string;
  type: string;
  required: boolean;
  rule: string;
}

/** 请求参数表（5.4） */
export const REQUEST_PARAMS: ParamRow[] = [
  { name: 'query', type: 'string', required: true, rule: '查询文本，去掉首尾空白后 1~1000 字' },
  {
    name: 'search_method',
    type: 'string',
    required: false,
    rule: 'vector（向量）/ full_text（全文）/ hybrid（混合）；不传使用知识库默认设置',
  },
  { name: 'top_k', type: 'int', required: false, rule: '1~20；不传使用知识库默认值' },
  {
    name: 'score_threshold',
    type: 'number',
    required: false,
    rule: '0~1；传入即启用阈值过滤，不传使用知识库默认值',
  },
  {
    name: 'reranking_enable',
    type: 'bool',
    required: false,
    rule: '仅对 vector / full_text 生效；为 true 时使用知识库默认设置中的 Rerank 模型，未配置则跳过并在 rerank_skipped 中说明',
  },
];

export const REQUEST_NOTES = [
  '知识库 ID 在路径中指定，一次只检索一个知识库；未知字段会被忽略。',
  '请求头 Authorization: Bearer <API 密钥>，Content-Type: application/json；可选 X-Request-Id 用于链路追踪，响应头同样返回 X-Request-Id。',
  '密钥的检索范围实时跟随创建人的权限：知识库不在范围内时与"不存在"返回相同错误。',
  '每个密钥每分钟的调用次数有上限（创建时设置，默认 60）；超限返回 429，响应头 Retry-After 为距下一分钟的秒数。',
];

/** curl 示例（与契约字段一致） */
export function buildCurl(endpoint: string): string {
  return [
    `curl -X POST "${endpoint}" \\`,
    `  -H "Authorization: Bearer kb-AbCd..." \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '{"query": "年假几天", "top_k": 3}'`,
  ].join('\n');
}

/** 带全部可选参数的 curl 示例 */
export function buildCurlFull(endpoint: string): string {
  return [
    `curl -X POST "${endpoint}" \\`,
    `  -H "Authorization: Bearer kb-AbCd..." \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '{"query": "年假几天", "search_method": "hybrid", "top_k": 5, "score_threshold": 0.5, "reranking_enable": false}'`,
  ].join('\n');
}

export function buildPython(endpoint: string): string {
  return [
    'import requests',
    '',
    'resp = requests.post(',
    `    "${endpoint}",`,
    '    headers={"Authorization": "Bearer kb-AbCd..."},',
    '    json={"query": "年假几天", "top_k": 3},',
    '    timeout=20,',
    ')',
    'body = resp.json()',
    'if body["code"] == 0:',
    '    for r in body["data"]["records"]:',
    '        print(r["score"], r["document"]["name"], r["content"])',
    'else:',
    '    print(body["code"], body["message"], body["data"]["error_type"])',
  ].join('\n');
}

export const SUCCESS_EXAMPLE = `{
  "code": 0,
  "message": "ok",
  "data": {
    "request_id": "req-7f3a...",
    "dataset": {"id": 10, "name": "集团制度"},
    "query": "年假几天",
    "retrieval_config": {
      "search_method": "hybrid", "top_k": 3, "score_threshold_enabled": false,
      "score_threshold": 0.5, "reranking_enable": false, "reranking_model_name": null,
      "hybrid_mode": "weighted", "vector_weight": 0.7
    },
    "rerank_skipped": false,
    "rerank_skipped_reason": null,
    "records": [
      {
        "segment_id": 5001, "position": 12, "segment_type": "general",
        "content": "年假为每年 10 天……", "score": 0.8731, "keywords": ["年假"],
        "document": {"id": 101, "name": "员工手册.pdf"},
        "dataset": {"id": 10, "name": "集团制度"},
        "child_chunks": []
      },
      {
        "segment_id": 6002, "position": 3, "segment_type": "parent",
        "content": "父块全文……", "score": 0.82, "keywords": [],
        "document": {"id": 120, "name": "制度汇编.docx"},
        "dataset": {"id": 10, "name": "集团制度"},
        "child_chunks": [
          {"id": 9001, "position": 2, "content": "子块……", "score": 0.82},
          {"id": 9002, "position": 3, "content": "子块……", "score": 0.75}
        ]
      }
    ]
  }
}`;

export const SUCCESS_NOTE =
  '同一知识库只会是一种分段方式：通用分段的 child_chunks 为空；父子分段时 content 为父块全文，child_chunks 为命中的子块。上例仅为展示两种结构。records 按 score 降序。';

export const ERROR_EXAMPLES = `// 知识库不存在或未授权（HTTP 404）
{"code": 404601, "message": "知识库不存在或未授权",
 "data": {"error_type": "DATASET_NOT_FOUND", "request_id": "req-..."}}

// 参数不合法（HTTP 400）
{"code": 400001, "message": "参数不合法",
 "data": {"error_type": "INVALID_PARAMS", "request_id": "req-...",
          "errors": [{"field": "top_k", "message": "取值范围 1~20"}]}}`;

/** 错误码与 error_type 表（5.0 / 5.4）；HTTP 状态 = code // 1000 */
export const ERROR_ROWS: OpenErrorRow[] = [
  { http: 401, code: 401601, errorType: 'KEY_INVALID', message: '密钥缺失或无效' },
  {
    http: 403,
    code: 403601,
    errorType: 'KEY_DISABLED',
    message: '密钥已停用',
    note: '含被管理员停用、创建人账号停用或失去"API 密钥"功能权限',
  },
  { http: 403, code: 403602, errorType: 'KEY_EXPIRED', message: '密钥已过期' },
  { http: 403, code: 403603, errorType: 'IP_NOT_ALLOWED', message: 'IP 不在白名单' },
  { http: 404, code: 404601, errorType: 'DATASET_NOT_FOUND', message: '知识库不存在或未授权' },
  {
    http: 400,
    code: 400001,
    errorType: 'INVALID_PARAMS',
    message: '参数不合法',
    note: 'data.errors 指出具体字段',
  },
  {
    http: 429,
    code: 429601,
    errorType: 'RATE_LIMITED',
    message: '调用超限，请下一分钟再试',
    note: '响应头 Retry-After 为距下一分钟的秒数',
  },
  { http: 503, code: 503601, errorType: 'MODEL_UNAVAILABLE', message: '模型服务不可用' },
  {
    http: 503,
    code: 503001,
    errorType: 'SERVICE_UNAVAILABLE',
    message: '依赖服务暂不可用，请稍后重试',
    note: '检索服务不可达或超时、依赖的缓存/数据库暂不可用等，可稍后重试',
  },
  { http: 500, code: 500000, errorType: 'INTERNAL_ERROR', message: '系统繁忙，请稍后重试' },
];
