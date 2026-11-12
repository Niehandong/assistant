import { PageHeader } from '@ant-design/pro-components';
import { App, Card, Result, Steps } from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { usePermission } from '@/access/usePermission';
import { uploadApi } from '@/services/kb';
import { KbErrorCode, type DuplicateFile } from '@/services/types/kb-contract';
import { isApiError } from '@/utils/error';
import { notifyError } from '@/utils/notify';
import { useEmbeddingMaxTokens } from '../useEmbeddingMax';
import { useDataset, useRefreshDataset } from '../useDataset';
import {
  defaultRule,
  fromProcessRule,
  ruleKey,
  toProcessRule,
  validateRule,
  type RuleFormValue,
} from './chunkRule';
import ChunkSettingStep, { type BlockedMap } from './components/ChunkSettingStep';
import FileSelectStep from './components/FileSelectStep';
import ProcessStep, { type SubmittedDoc } from './components/ProcessStep';
import {
  MAX_FILES,
  UPLOAD_CONCURRENCY,
  doneItems,
  isBusy,
  limitFiles,
  runWithConcurrency,
  toUploadItems,
  uploadErrorMessage,
  type UploadItem,
} from './fileCheck';

export default function UploadPage() {
  const dataset = useDataset();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const can = usePermission();
  const refreshDataset = useRefreshDataset(dataset.id);
  const maxInput = useEmbeddingMaxTokens(dataset);

  const [step, setStep] = useState(0);
  const [items, setItems] = useState<UploadItem[]>([]);
  const [rule, setRuleState] = useState<RuleFormValue>(() =>
    dataset.last_process_rule
      ? {
          ...fromProcessRule(dataset.last_process_rule, dataset.chunk_mode ?? 'general'),
          ...(dataset.chunk_mode ? { mode: dataset.chunk_mode } : {}),
        }
      : defaultRule(dataset.chunk_mode ?? 'general'),
  );
  // 仅当规则仍是未被用户修改的默认值时，才按模型上限自动夹取默认长度
  const ruleTouched = useRef(!!dataset.last_process_rule);
  const setRule = useCallback((v: RuleFormValue) => {
    ruleTouched.current = true;
    setRuleState(v);
  }, []);
  useEffect(() => {
    if (ruleTouched.current || maxInput == null) return;
    setRuleState(defaultRule(dataset.chunk_mode ?? 'general', maxInput));
  }, [maxInput, dataset.chunk_mode]);
  const [blocked, setBlocked] = useState<BlockedMap>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState<SubmittedDoc[]>([]);

  const itemsRef = useRef<UploadItem[]>([]);
  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  const patch = useCallback((uid: string, p: Partial<UploadItem>) => {
    setItems((prev) => prev.map((i) => (i.uid === uid ? { ...i, ...p } : i)));
  }, []);

  const uploadOne = useCallback(
    async (it: UploadItem) => {
      patch(it.uid, { status: 'uploading', progress: 0, error: undefined });
      try {
        const res = await uploadApi.upload(dataset.id, it.file, (percent) =>
          patch(it.uid, { progress: percent }),
        );
        patch(it.uid, { status: 'done', progress: 100, uploadFileId: res.upload_file_id });
      } catch (err) {
        patch(it.uid, { status: 'error', error: uploadErrorMessage(err) });
      }
    },
    [dataset.id, patch],
  );

  const handleAdd = (files: File[]) => {
    const [accepted, dropped] = limitFiles(itemsRef.current.length, files);
    if (dropped > 0) {
      void message.warning(`一次最多选择 ${MAX_FILES} 个文件，已忽略多出的 ${dropped} 个`);
    }
    if (accepted.length === 0) return;
    const created = toUploadItems(accepted);
    setItems((prev) => [...prev, ...created]);
    void runWithConcurrency(
      created.filter((i) => i.status === 'queued'),
      UPLOAD_CONCURRENCY,
      uploadOne,
    );
  };

  const handleRetry = (uid: string) => {
    const it = itemsRef.current.find((i) => i.uid === uid);
    if (it) void uploadOne(it);
  };

  const done = doneItems(items);
  const ruleValid = Object.keys(validateRule(rule, maxInput)).length === 0;

  const handleSubmit = async () => {
    if (!ruleValid) return;
    const key = ruleKey(rule);
    const ids = done
      .filter((i) => i.uploadFileId !== undefined && blocked[i.uploadFileId]?.key !== key)
      .map((i) => i.uploadFileId as number);
    if (ids.length === 0) return;
    setSubmitting(true);
    try {
      const res = await uploadApi.submit(dataset.id, {
        upload_file_ids: ids,
        process_rule: toProcessRule(rule),
      });
      setSubmitted(res.documents);
      setStep(2);
      void refreshDataset();
    } catch (err) {
      if (isApiError(err) && err.code === KbErrorCode.DUPLICATE_CONTENT) {
        const dups = (err.data as { duplicates?: DuplicateFile[] } | null)?.duplicates ?? [];
        setItems((prev) =>
          prev.map((i) => {
            const d = dups.find((x) => x.upload_file_id === i.uploadFileId);
            return d
              ? {
                  ...i,
                  status: 'error',
                  uploadFileId: undefined,
                  error: `与已有文档《${d.existing_document_name}》内容重复`,
                }
              : i;
          }),
        );
        void message.error('部分文件与已有文档内容重复，已标红，请移除后再提交');
        if (dups.length > 0 && done.length === dups.length) setStep(0);
      } else {
        notifyError(err);
        if (isApiError(err) && err.code === KbErrorCode.CHUNK_MODE_LOCKED) void refreshDataset();
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (!can('kb:document:upload') || dataset.my_permission === 'read') {
    return <Result status="403" title="您没有上传文档的权限" />;
  }
  if (dataset.embedding_model.status === 'disabled') {
    return <Result status="warning" title="向量模型已停用，请联系管理员" />;
  }

  const backToList = () => navigate(`/kb/datasets/${dataset.id}/documents`);

  return (
    <Card>
      <PageHeader title="上传文档" onBack={backToList} style={{ paddingInline: 0 }} />
      <Steps
        current={step}
        style={{ margin: '8px 0 24px' }}
        items={[{ title: '选择文件' }, { title: '分段设置与预览' }, { title: '处理进度' }]}
      />
      {step === 0 && (
        <FileSelectStep
          items={items}
          onAdd={handleAdd}
          onRemove={(uid) => setItems((prev) => prev.filter((i) => i.uid !== uid))}
          onRetry={handleRetry}
          onNext={() => setStep(1)}
          nextDisabled={done.length === 0 || isBusy(items)}
        />
      )}
      {step === 1 && (
        <ChunkSettingStep
          dataset={dataset}
          files={done}
          rule={rule}
          onRuleChange={setRule}
          maxInputTokens={maxInput}
          blocked={blocked}
          onBlock={(id, key, msg) => setBlocked((b) => ({ ...b, [id]: { key, message: msg } }))}
          onExpired={(id, msg) =>
            setItems((prev) =>
              prev.map((i) =>
                i.uploadFileId === id
                  ? { ...i, status: 'error', uploadFileId: undefined, error: msg }
                  : i,
              ),
            )
          }
          onBack={() => setStep(0)}
          onSubmit={() => void handleSubmit()}
          submitting={submitting}
        />
      )}
      {step === 2 && (
        <ProcessStep
          datasetId={dataset.id}
          docs={submitted}
          onBackToList={backToList}
          onAllDone={() => void refreshDataset()}
        />
      )}
    </Card>
  );
}
