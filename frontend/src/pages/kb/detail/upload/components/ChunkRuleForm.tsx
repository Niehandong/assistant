import { Alert, Button, Checkbox, Form, Input, InputNumber, Radio, Space } from 'antd';
import type { ReactNode } from 'react';
import type { ChunkMode } from '@/services/types/kb-contract';
import {
  defaultRule,
  fromProcessRule,
  validateRule,
  type RuleErrors,
  type RuleFormValue,
} from '../chunkRule';

interface Props {
  value: RuleFormValue;
  onChange: (v: RuleFormValue) => void;
  /** 知识库已确定的分段方式：非空时锁定不可切换 */
  lockedMode?: ChunkMode | null;
  /** 所选 Embedding 模型单次最大输入 */
  maxInputTokens?: number | null;
  /** 知识库上次使用的规则（last_process_rule）；为空时不显示“使用上次设置” */
  lastRule?: unknown;
  /** 是否显示快捷操作（重新分段弹窗也复用） */
  showShortcuts?: boolean;
  disabled?: boolean;
}

function Field({
  label,
  error,
  extra,
  children,
}: {
  label: string;
  error?: string;
  extra?: string;
  children: ReactNode;
}) {
  return (
    <Form.Item
      label={label}
      required
      validateStatus={error ? 'error' : undefined}
      help={error ?? extra}
    >
      {children}
    </Form.Item>
  );
}

/** 分段设置表单（受控；通用 / 父子 + 文本预处理 + 快捷操作），FE-11 重新分段弹窗复用 */
export default function ChunkRuleForm({
  value,
  onChange,
  lockedMode,
  maxInputTokens,
  lastRule,
  showShortcuts = true,
  disabled,
}: Props) {
  const errors: RuleErrors = validateRule(value, maxInputTokens);
  const set = (patch: Partial<RuleFormValue>) => onChange({ ...value, ...patch });
  const fullDoc = value.mode === 'parent_child' && value.parent.mode === 'full_doc';
  const num = (v: number | string | null) => (typeof v === 'number' ? v : null);

  return (
    <Form layout="vertical" disabled={disabled}>
      <Form.Item
        label="分段方式"
        extra={
          lockedMode
            ? '该知识库已确定分段方式，不能切换（删除全部文档后可重新选择）'
            : '首次上传时二选一，之后该知识库固定使用此方式'
        }
      >
        <Radio.Group
          value={value.mode}
          disabled={disabled || !!lockedMode}
          onChange={(e) => set({ mode: e.target.value })}
          options={[
            { value: 'general', label: '通用分段' },
            { value: 'parent_child', label: '父子分段' },
          ]}
          optionType="button"
        />
      </Form.Item>

      {value.mode === 'general' ? (
        <>
          <Field
            label="分段标识符"
            error={errors['general.separator']}
            extra="支持 \n、\n\n 等转义写法，1~10 个字符"
          >
            <Input
              aria-label="分段标识符"
              value={value.general.separator}
              onChange={(e) => set({ general: { ...value.general, separator: e.target.value } })}
              style={{ maxWidth: 240 }}
            />
          </Field>
          <Field
            label="分段最大长度（tokens）"
            error={errors['general.max_tokens']}
            extra="50~4000，且不超过向量模型单次最大输入"
          >
            <InputNumber
              aria-label="分段最大长度"
              precision={0}
              value={value.general.max_tokens}
              onChange={(v) => set({ general: { ...value.general, max_tokens: num(v) } })}
            />
          </Field>
          <Field
            label="分段重叠长度（tokens）"
            error={errors['general.chunk_overlap']}
            extra="0 ~ 最大长度的 50%"
          >
            <InputNumber
              aria-label="分段重叠长度"
              precision={0}
              value={value.general.chunk_overlap}
              onChange={(v) => set({ general: { ...value.general, chunk_overlap: num(v) } })}
            />
          </Field>
        </>
      ) : (
        <>
          <Form.Item label="父块模式">
            <Radio.Group
              value={value.parent.mode}
              onChange={(e) => set({ parent: { ...value.parent, mode: e.target.value } })}
              options={[
                { value: 'paragraph', label: '段落' },
                { value: 'full_doc', label: '全文' },
              ]}
            />
          </Form.Item>
          {fullDoc ? (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message="全文模式：整篇文档作为一个父块，仅适用于不超过 10,000 tokens 的文档"
            />
          ) : (
            <>
              <Field
                label="父块分隔符"
                error={errors['parent.separator']}
                extra="支持转义写法，1~10 个字符"
              >
                <Input
                  aria-label="父块分隔符"
                  value={value.parent.separator}
                  onChange={(e) => set({ parent: { ...value.parent, separator: e.target.value } })}
                  style={{ maxWidth: 240 }}
                />
              </Field>
              <Field
                label="父块最大长度（tokens）"
                error={errors['parent.max_tokens']}
                extra="50~4000"
              >
                <InputNumber
                  aria-label="父块最大长度"
                  precision={0}
                  value={value.parent.max_tokens}
                  onChange={(v) => set({ parent: { ...value.parent, max_tokens: num(v) } })}
                />
              </Field>
            </>
          )}
          <Field
            label="子块分隔符"
            error={errors['child.separator']}
            extra="支持转义写法，1~10 个字符"
          >
            <Input
              aria-label="子块分隔符"
              value={value.child.separator}
              onChange={(e) => set({ child: { ...value.child, separator: e.target.value } })}
              style={{ maxWidth: 240 }}
            />
          </Field>
          <Field
            label="子块最大长度（tokens）"
            error={errors['child.max_tokens']}
            extra={`20 ~ ${fullDoc ? 4000 : '父块最大长度'}，且不超过向量模型单次最大输入`}
          >
            <InputNumber
              aria-label="子块最大长度"
              precision={0}
              value={value.child.max_tokens}
              onChange={(v) => set({ child: { ...value.child, max_tokens: num(v) } })}
            />
          </Field>
        </>
      )}

      <Form.Item label="文本预处理">
        <Space direction="vertical">
          <Checkbox
            checked={value.normalize_whitespace}
            onChange={(e) => set({ normalize_whitespace: e.target.checked })}
          >
            替换连续空格、换行符和制表符
          </Checkbox>
          <Checkbox
            checked={value.remove_urls_emails}
            onChange={(e) => set({ remove_urls_emails: e.target.checked })}
          >
            删除所有 URL 和电子邮件地址
          </Checkbox>
        </Space>
      </Form.Item>

      {showShortcuts && (
        <Space>
          {!!lastRule && (
            <Button
              disabled={disabled}
              onClick={() => {
                const restored = fromProcessRule(lastRule, lockedMode ?? value.mode);
                onChange(lockedMode ? { ...restored, mode: lockedMode } : restored);
              }}
            >
              使用该知识库上次的设置
            </Button>
          )}
          <Button
            disabled={disabled}
            onClick={() => onChange(defaultRule(lockedMode ?? value.mode, maxInputTokens))}
          >
            恢复默认
          </Button>
        </Space>
      )}
    </Form>
  );
}
