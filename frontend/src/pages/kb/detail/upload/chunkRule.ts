import type {
  ChunkMode,
  GeneralProcessRule,
  ParentChildProcessRule,
  ProcessRule,
} from '@/services/types/kb-contract';

/** 分段设置的界面状态（两种方式的字段同时保留，切换方式不丢输入） */
export interface RuleFormValue {
  mode: ChunkMode;
  normalize_whitespace: boolean;
  remove_urls_emails: boolean;
  general: { separator: string; max_tokens: number | null; chunk_overlap: number | null };
  parent: { mode: 'paragraph' | 'full_doc'; separator: string; max_tokens: number | null };
  child: { separator: string; max_tokens: number | null };
}

export const DEFAULT_RULE: RuleFormValue = {
  mode: 'general',
  normalize_whitespace: true,
  remove_urls_emails: false,
  general: { separator: '\\n\\n', max_tokens: 1024, chunk_overlap: 50 },
  parent: { mode: 'paragraph', separator: '\\n\\n', max_tokens: 1024 },
  child: { separator: '\\n', max_tokens: 512 },
};

/**
 * 默认规则：保持当前（可能被锁定的）分段方式。
 * maxInputTokens 已知时，通用分段最大长度与子块最大长度默认取 min(默认值, 模型上限)，
 * 避免默认值直接超过模型单次最大输入；父块不受 embedding 上限约束，保持不变。
 */
export function defaultRule(
  mode: ChunkMode = 'general',
  maxInputTokens?: number | null,
): RuleFormValue {
  const rule = structuredClone({ ...DEFAULT_RULE, mode });
  if (typeof maxInputTokens === 'number' && maxInputTokens > 0) {
    rule.general.max_tokens = Math.min(DEFAULT_RULE.general.max_tokens ?? 1024, maxInputTokens);
    rule.child.max_tokens = Math.min(DEFAULT_RULE.child.max_tokens ?? 512, maxInputTokens);
  }
  return rule;
}

export const SEPARATOR_MAX_LEN = 10;
export const FULL_DOC_MAX_TOKENS = 10000;

export type RuleErrors = Record<string, string>;

const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v);

function checkSeparator(v: string, key: string, label: string, errors: RuleErrors) {
  if (v.length < 1 || v.length > SEPARATOR_MAX_LEN) {
    errors[key] = `${label}须为 1~${SEPARATOR_MAX_LEN} 个字符`;
  }
}

/**
 * 校验规则（与 tech-design-m2 3.5 一致，AC-39）。key 为字段路径：
 * general.separator / general.max_tokens / general.chunk_overlap /
 * parent.separator / parent.max_tokens / child.separator / child.max_tokens
 * maxInputTokens：所选 Embedding 模型的单次最大输入（未知时不校验该上限）。
 */
export function validateRule(v: RuleFormValue, maxInputTokens?: number | null): RuleErrors {
  const errors: RuleErrors = {};
  const cap = maxInputTokens ?? Number.POSITIVE_INFINITY;
  if (v.mode === 'general') {
    const g = v.general;
    checkSeparator(g.separator, 'general.separator', '分段标识符', errors);
    if (!isInt(g.max_tokens) || g.max_tokens < 50 || g.max_tokens > 4000) {
      errors['general.max_tokens'] = '分段最大长度须为 50~4000 的整数';
    } else if (g.max_tokens > cap) {
      errors['general.max_tokens'] = `不能超过所选向量模型的单次最大输入（${cap} tokens）`;
    }
    const maxOverlap = isInt(g.max_tokens) ? Math.floor(g.max_tokens * 0.5) : 0;
    if (!isInt(g.chunk_overlap) || g.chunk_overlap < 0 || g.chunk_overlap > maxOverlap) {
      errors['general.chunk_overlap'] = `重叠长度须为 0~${maxOverlap}（最大长度的 50%）的整数`;
    }
    return errors;
  }
  const p = v.parent;
  const paragraph = p.mode === 'paragraph';
  if (paragraph) {
    checkSeparator(p.separator, 'parent.separator', '父块分隔符', errors);
    if (!isInt(p.max_tokens) || p.max_tokens < 50 || p.max_tokens > 4000) {
      errors['parent.max_tokens'] = '父块最大长度须为 50~4000 的整数';
    }
  }
  checkSeparator(v.child.separator, 'child.separator', '子块分隔符', errors);
  const childUpper =
    paragraph && isInt(p.max_tokens) && !errors['parent.max_tokens'] ? p.max_tokens : 4000;
  const c = v.child.max_tokens;
  if (!isInt(c) || c < 20 || c > childUpper) {
    errors['child.max_tokens'] = `子块最大长度须为 20~${childUpper} 的整数${
      paragraph ? '（不超过父块最大长度）' : ''
    }`;
  } else if (c > cap) {
    errors['child.max_tokens'] = `不能超过所选向量模型的单次最大输入（${cap} tokens）`;
  }
  return errors;
}

/** 转为接口 process_rule（调用前需先校验通过） */
export function toProcessRule(v: RuleFormValue): ProcessRule {
  const pre = {
    normalize_whitespace: v.normalize_whitespace,
    remove_urls_emails: v.remove_urls_emails,
  };
  if (v.mode === 'general') {
    return {
      mode: 'general',
      pre_processing: pre,
      general: {
        separator: v.general.separator,
        max_tokens: v.general.max_tokens ?? 0,
        chunk_overlap: v.general.chunk_overlap ?? 0,
      },
    } satisfies GeneralProcessRule;
  }
  return {
    mode: 'parent_child',
    pre_processing: pre,
    parent: {
      mode: v.parent.mode,
      separator: v.parent.separator,
      max_tokens: v.parent.max_tokens ?? 0,
    },
    child: { separator: v.child.separator, max_tokens: v.child.max_tokens ?? 0 },
  } satisfies ParentChildProcessRule;
}

/** 从接口规则（last_process_rule / 文档 process_rule）还原界面状态；缺失字段用默认值 */
export function fromProcessRule(rule: unknown, fallbackMode: ChunkMode = 'general'): RuleFormValue {
  const base = defaultRule(fallbackMode);
  if (!rule || typeof rule !== 'object') return base;
  const r = rule as Partial<ProcessRule> & Record<string, unknown>;
  if (r.mode !== 'general' && r.mode !== 'parent_child') return base;
  const pre = (r.pre_processing ?? {}) as Partial<ProcessRule['pre_processing']>;
  const out: RuleFormValue = {
    ...base,
    mode: r.mode,
    normalize_whitespace: pre.normalize_whitespace ?? base.normalize_whitespace,
    remove_urls_emails: pre.remove_urls_emails ?? base.remove_urls_emails,
  };
  if (r.mode === 'general' && 'general' in r && r.general) {
    out.general = { ...base.general, ...(r.general as Partial<RuleFormValue['general']>) };
  }
  if (r.mode === 'parent_child') {
    if ('parent' in r && r.parent) {
      out.parent = { ...base.parent, ...(r.parent as Partial<RuleFormValue['parent']>) };
    }
    if ('child' in r && r.child) {
      out.child = { ...base.child, ...(r.child as Partial<RuleFormValue['child']>) };
    }
  }
  return out;
}

/** 规则稳定指纹：规则变化后，之前的预览失败（400505/400506）标记作废 */
export function ruleKey(v: RuleFormValue): string {
  return JSON.stringify(toProcessRule(v));
}
