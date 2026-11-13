import { Form, InputNumber, Radio, Select, Slider, Space, Switch, Tooltip, Typography } from 'antd';
import type { ModelOption, RetrievalConfig } from '@/services/types/kb-contract';
import {
  changeSearchMethod,
  keywordWeight,
  validateRetrievalConfig,
  type RetrievalErrors,
} from './retrievalConfig';

interface Props {
  value: RetrievalConfig;
  onChange: (v: RetrievalConfig) => void;
  /** 已启用的 Rerank 模型（来自 /models/options?model_type=rerank） */
  rerankModels: ModelOption[];
  rerankLoading?: boolean;
  disabled?: boolean;
  /** 外部控制的错误；缺省时按 value 实时校验 */
  errors?: RetrievalErrors;
}

const SEARCH_OPTIONS = [
  { value: 'vector', label: '向量检索' },
  { value: 'full_text', label: '全文检索' },
  { value: 'hybrid', label: '混合检索' },
] as const;

const HELP: Record<RetrievalConfig['search_method'], string> = {
  vector: '按语义相似度检索',
  full_text: '按关键词匹配检索',
  hybrid: '同时执行向量检索和全文检索，再合并结果',
};

/** 检索设置表单（受控）：设置页与召回测试页共用 */
export default function RetrievalConfigForm({
  value,
  onChange,
  rerankModels,
  rerankLoading,
  disabled,
  errors,
}: Props) {
  const errs = errors ?? validateRetrievalConfig(value, rerankModels);
  const set = (patch: Partial<RetrievalConfig>) => onChange({ ...value, ...patch });
  const noRerank = rerankModels.length === 0;
  const hybrid = value.search_method === 'hybrid';

  const rerankSelect = (
    <Form.Item
      label="Rerank 模型"
      required
      validateStatus={errs.reranking_model_id ? 'error' : undefined}
      help={errs.reranking_model_id}
    >
      <Select
        aria-label="Rerank 模型"
        placeholder="请选择 Rerank 模型"
        disabled={disabled || noRerank}
        loading={rerankLoading}
        value={value.reranking_model_id ?? undefined}
        onChange={(v) => set({ reranking_model_id: v })}
        options={rerankModels.map((m) => ({ value: m.id, label: m.name }))}
        style={{ maxWidth: 320 }}
      />
    </Form.Item>
  );

  return (
    <Form layout="vertical" disabled={disabled}>
      <Form.Item label="检索方式" extra={HELP[value.search_method]}>
        <Radio.Group
          value={value.search_method}
          options={SEARCH_OPTIONS as unknown as { value: string; label: string }[]}
          optionType="button"
          onChange={(e) => onChange(changeSearchMethod(value, e.target.value))}
        />
      </Form.Item>

      {hybrid && (
        <>
          <Form.Item label="结果合并方式">
            <Radio.Group
              value={value.hybrid_mode}
              onChange={(e) => set({ hybrid_mode: e.target.value })}
              options={[
                { value: 'weighted', label: '权重' },
                { value: 'rerank', label: 'Rerank 模型重排' },
              ]}
            />
          </Form.Item>
          {value.hybrid_mode === 'weighted' ? (
            <Form.Item
              label="语义权重"
              validateStatus={errs.vector_weight ? 'error' : undefined}
              help={errs.vector_weight}
            >
              <Slider
                min={0}
                max={1}
                step={0.1}
                value={value.vector_weight}
                onChange={(v) => set({ vector_weight: v })}
                style={{ maxWidth: 360 }}
                aria-label="语义权重"
              />
              <Typography.Text type="secondary">
                语义 {value.vector_weight.toFixed(1)} / 关键词{' '}
                {keywordWeight(value.vector_weight).toFixed(1)}
              </Typography.Text>
            </Form.Item>
          ) : (
            rerankSelect
          )}
        </>
      )}

      {!hybrid && (
        <Form.Item
          label="Rerank"
          extra={noRerank ? '暂无启用的 Rerank 模型，请联系管理员在“模型配置”中启用' : undefined}
        >
          <Tooltip title={noRerank ? '暂无启用的 Rerank 模型' : undefined}>
            <Switch
              aria-label="开启 Rerank"
              checked={value.reranking_enable}
              disabled={disabled || noRerank}
              onChange={(v) => set({ reranking_enable: v })}
            />
          </Tooltip>
        </Form.Item>
      )}
      {!hybrid && value.reranking_enable && rerankSelect}

      <Form.Item
        label="Top K"
        required
        validateStatus={errs.top_k ? 'error' : undefined}
        help={errs.top_k ?? '返回条数上限，1~20'}
      >
        <InputNumber
          aria-label="Top K"
          min={0}
          max={100}
          precision={0}
          value={value.top_k}
          onChange={(v) => set({ top_k: v as number })}
        />
      </Form.Item>

      <Form.Item
        label="Score 阈值"
        validateStatus={errs.score_threshold ? 'error' : undefined}
        help={errs.score_threshold ?? '开启后，得分低于阈值的结果不返回'}
      >
        <Space>
          <Switch
            aria-label="开启 Score 阈值"
            checked={value.score_threshold_enabled}
            onChange={(v) => set({ score_threshold_enabled: v })}
          />
          <InputNumber
            aria-label="Score 阈值"
            min={0}
            max={5}
            step={0.01}
            precision={2}
            disabled={disabled || !value.score_threshold_enabled}
            value={value.score_threshold}
            onChange={(v) => set({ score_threshold: v as number })}
          />
        </Space>
      </Form.Item>
    </Form>
  );
}
