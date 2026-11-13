import { Alert, App, Button, Drawer, Form, Input, Select, Space, Typography } from 'antd';
import { useState } from 'react';
import type { SegmentItem } from '@/services/types/kb-contract';
import {
  KEYWORD_MAX_COUNT,
  KEYWORD_MAX_LENGTH,
  REGENERATE_CONFIRM_TEXT,
  checkContent,
  normalizeKeywords,
  validateKeywords,
} from '../logic';
import type { SaveResult } from '../useSegmentActions';

interface Props {
  /** null = 新增通用分段 */
  segment: SegmentItem | null;
  /** 新增模式下的分段类型固定为通用 */
  open: boolean;
  /** 只读：只展示，不显示保存 */
  readonly: boolean;
  limit: number | null;
  onClose: () => void;
  onSubmit: (form: { content: string; keywords: string[] }) => Promise<SaveResult>;
}

/** 分段详情/编辑抽屉：通用分段含关键词；父块保存前二次确认会重建子块 */
export default function SegmentDrawer({
  segment,
  open,
  readonly,
  limit,
  onClose,
  onSubmit,
}: Props) {
  const { modal } = App.useApp();
  const isParent = segment?.segment_type === 'parent';
  const [content, setContent] = useState(segment?.content ?? '');
  const [keywords, setKeywords] = useState<string[]>(segment?.keywords ?? []);
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const check = checkContent(content, limit);
  const kwError = isParent ? null : validateKeywords(keywords);
  const invalid = !!check.error || !!kwError;
  const title = readonly
    ? `分段详情 #${segment?.position ?? ''}`
    : segment
      ? `编辑${isParent ? '父块' : '分段'} #${segment.position}`
      : '新增分段';

  const doSave = async () => {
    setSaving(true);
    setServerError(null);
    const r = await onSubmit({ content, keywords: normalizeKeywords(keywords) });
    setSaving(false);
    if (r.ok) onClose();
    else if (r.kind === 'conflict') onClose();
    else setServerError(r.message);
  };

  const submit = () => {
    if (invalid) return;
    if (isParent) {
      modal.confirm({
        title: '确认保存父块？',
        content: REGENERATE_CONFIRM_TEXT,
        okText: '确认保存',
        onOk: doSave,
      });
    } else {
      void doSave();
    }
  };

  return (
    <Drawer
      title={title}
      open={open}
      width={560}
      onClose={onClose}
      destroyOnClose
      extra={
        !readonly && (
          <Space>
            <Button onClick={onClose}>取消</Button>
            <Button type="primary" loading={saving} disabled={invalid} onClick={submit}>
              保存
            </Button>
          </Space>
        )
      }
    >
      <Form layout="vertical">
        {serverError && (
          <Alert type="error" showIcon message={serverError} style={{ marginBottom: 16 }} />
        )}
        <Form.Item
          label="内容"
          required={!readonly}
          validateStatus={!readonly && content !== '' && check.error ? 'error' : undefined}
          help={!readonly && content !== '' ? (check.error ?? check.warning) : undefined}
        >
          <Input.TextArea
            aria-label="分段内容"
            rows={14}
            value={content}
            readOnly={readonly}
            onChange={(e) => setContent(e.target.value)}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {content.trim().length} 字符{limit !== null ? ` / 上限 ${limit} tokens` : ''}
          </Typography.Text>
        </Form.Item>
        {isParent && !readonly && (
          <Alert
            type="info"
            showIcon
            message={REGENERATE_CONFIRM_TEXT}
            style={{ marginBottom: 16 }}
          />
        )}
        {!isParent && (
          <Form.Item
            label="关键词"
            validateStatus={kwError ? 'error' : undefined}
            help={
              kwError ??
              `最多 ${KEYWORD_MAX_COUNT} 个，每个不超过 ${KEYWORD_MAX_LENGTH} 字，用于全文检索加权`
            }
          >
            <Select
              aria-label="关键词"
              mode="tags"
              open={false}
              tokenSeparators={[',', '，']}
              value={keywords}
              disabled={readonly}
              onChange={(v: string[]) => setKeywords(v)}
              placeholder={readonly ? '无关键词' : '输入后回车添加'}
            />
          </Form.Item>
        )}
      </Form>
    </Drawer>
  );
}
