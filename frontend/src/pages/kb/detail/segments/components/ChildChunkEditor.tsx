import { Alert, Form, Input, Modal, Typography } from 'antd';
import { useState } from 'react';
import type { ChildChunkItem } from '@/services/types/kb-contract';
import { checkContent } from '../logic';
import type { SaveResult } from '../useSegmentActions';

interface Props {
  open: boolean;
  /** null = 新增子块 */
  child: ChildChunkItem | null;
  limit: number | null;
  onClose: () => void;
  onSubmit: (content: string) => Promise<SaveResult>;
}

/** 子块新增/编辑弹窗 */
export default function ChildChunkEditor({ open, child, limit, onClose, onSubmit }: Props) {
  const [content, setContent] = useState(child?.content ?? '');
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const check = checkContent(content, limit);

  const save = async () => {
    if (check.error) return;
    setSaving(true);
    const r = await onSubmit(content);
    setSaving(false);
    if (r.ok || r.kind === 'conflict') onClose();
    else setServerError(r.message);
  };

  return (
    <Modal
      title={child ? `编辑子块 #${child.position}` : '新增子块'}
      open={open}
      onCancel={onClose}
      onOk={() => void save()}
      okText="保存"
      okButtonProps={{ disabled: !!check.error, loading: saving }}
      destroyOnClose
    >
      {serverError && (
        <Alert type="error" showIcon message={serverError} style={{ marginBottom: 12 }} />
      )}
      <Form layout="vertical">
        <Form.Item
          label="子块内容"
          required
          validateStatus={content !== '' && check.error ? 'error' : undefined}
          help={content !== '' ? (check.error ?? check.warning) : undefined}
        >
          <Input.TextArea
            aria-label="子块内容"
            rows={6}
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {content.trim().length} 字符{limit !== null ? ` / 上限 ${limit} tokens` : ''}
          </Typography.Text>
        </Form.Item>
      </Form>
    </Modal>
  );
}
