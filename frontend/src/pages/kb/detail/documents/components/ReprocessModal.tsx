import { Alert, App, Modal } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { documentApi } from '@/services/kb';
import type { DatasetDetail, DocumentItem } from '@/services/types/kb-contract';
import { notifyError } from '@/utils/notify';
import { useEmbeddingMaxTokens } from '../../useEmbeddingMax';
import {
  defaultRule,
  fromProcessRule,
  toProcessRule,
  validateRule,
  type RuleFormValue,
} from '../../upload/chunkRule';
import ChunkRuleForm from '../../upload/components/ChunkRuleForm';

interface Props {
  dataset: DatasetDetail;
  doc: DocumentItem;
  onClose: () => void;
  onSuccess: () => void;
}

/** 重新分段：分段方式锁定为知识库当前方式，仅可调整参数；确认会丢弃全部现有分段及人工修改 */
export default function ReprocessModal({ dataset, doc, onClose, onSuccess }: Props) {
  const { message } = App.useApp();
  const mode = dataset.chunk_mode ?? doc.chunk_mode;
  const maxInput = useEmbeddingMaxTokens(dataset);
  const [edited, setEdited] = useState<RuleFormValue | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { data: detail, isLoading } = useQuery({
    queryKey: ['kb-document-detail', dataset.id, doc.id],
    queryFn: () => documentApi.detail(dataset.id, doc.id),
  });

  // 初始值：文档当前规则 > 知识库上次设置 > 默认
  const initial: RuleFormValue = detail?.process_rule
    ? { ...fromProcessRule(detail.process_rule, mode), mode }
    : dataset.last_process_rule
      ? { ...fromProcessRule(dataset.last_process_rule, mode), mode }
      : defaultRule(mode);
  const value = edited ?? initial;
  const errors = validateRule(value, maxInput);
  const invalid = Object.keys(errors).length > 0;

  const submit = async () => {
    setSubmitting(true);
    try {
      await documentApi.reprocess(dataset.id, doc.id, {
        process_rule: toProcessRule(value),
        version: detail?.version ?? doc.version,
      });
      void message.success('已提交重新分段');
      onSuccess();
    } catch (err) {
      notifyError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open
      width={640}
      title={`重新分段：${doc.name}`}
      okText="确认并重新处理"
      okButtonProps={{ danger: true, disabled: invalid || isLoading, loading: submitting }}
      maskClosable={false}
      destroyOnClose
      onOk={submit}
      onCancel={onClose}
    >
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="将丢弃全部现有分段及人工修改"
        description="确认后该文档重新进入处理流程，处理完成前不参与检索。"
      />
      <ChunkRuleForm
        value={value}
        onChange={setEdited}
        lockedMode={mode}
        maxInputTokens={maxInput}
        lastRule={dataset.last_process_rule}
        disabled={isLoading}
      />
    </Modal>
  );
}
