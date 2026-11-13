import { Alert, Button, Card, Col, Row, Select, Space } from 'antd';
import { useState } from 'react';
import { uploadApi } from '@/services/kb';
import { KbErrorCode, type DatasetDetail, type PreviewResult } from '@/services/types/kb-contract';
import { isApiError } from '@/utils/error';
import { notifyError } from '@/utils/notify';
import { ruleKey, toProcessRule, validateRule, type RuleFormValue } from '../chunkRule';
import type { UploadItem } from '../fileCheck';
import ChunkRuleForm from './ChunkRuleForm';
import PreviewPanel from './PreviewPanel';

/** 预览失败导致不可提交的文件（记录当时的规则指纹，规则变化后作废） */
export type BlockedMap = Record<number, { key: string; message: string }>;

interface Props {
  dataset: DatasetDetail;
  /** 已上传成功的文件 */
  files: UploadItem[];
  rule: RuleFormValue;
  onRuleChange: (v: RuleFormValue) => void;
  maxInputTokens?: number | null;
  blocked: BlockedMap;
  onBlock: (uploadFileId: number, key: string, message: string) => void;
  /** 400508：上传文件已失效 */
  onExpired: (uploadFileId: number, message: string) => void;
  onBack: () => void;
  onSubmit: () => void;
  submitting: boolean;
}

export default function ChunkSettingStep({
  dataset,
  files,
  rule,
  onRuleChange,
  maxInputTokens,
  blocked,
  onBlock,
  onExpired,
  onBack,
  onSubmit,
  submitting,
}: Props) {
  const [selectedId, setSelectedId] = useState<number | undefined>(files[0]?.uploadFileId);
  const [preview, setPreview] = useState<{
    fileId: number;
    key: string;
    data: PreviewResult;
  } | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const errors = validateRule(rule, maxInputTokens);
  const valid = Object.keys(errors).length === 0;
  const key = valid ? ruleKey(rule) : '';
  const activeId = files.some((f) => f.uploadFileId === selectedId)
    ? selectedId
    : files[0]?.uploadFileId;
  const isBlocked = (id: number) => blocked[id]?.key === key && !!key;
  const submittable = files.filter(
    (f) => f.uploadFileId !== undefined && !isBlocked(f.uploadFileId),
  );
  const activeBlock = activeId !== undefined && isBlocked(activeId) ? blocked[activeId] : null;
  const stale = preview && preview.key !== key;

  const runPreview = async () => {
    if (!valid || activeId === undefined) return;
    setPreviewing(true);
    setPreviewError(null);
    try {
      const data = await uploadApi.preview(dataset.id, {
        upload_file_id: activeId,
        process_rule: toProcessRule(rule),
      });
      setPreview({ fileId: activeId, key, data });
    } catch (err) {
      setPreview(null);
      if (
        isApiError(err) &&
        (err.code === KbErrorCode.NO_TEXT || err.code === KbErrorCode.DOC_TOO_LONG)
      ) {
        onBlock(activeId, key, err.message);
      } else if (isApiError(err) && err.code === KbErrorCode.UPLOAD_EXPIRED) {
        onExpired(activeId, err.message);
      } else if (isApiError(err) && err.code === 400001) {
        setPreviewError('分段参数不合法，请检查后重试');
      } else {
        notifyError(err);
        setPreviewError(err instanceof Error ? err.message : '预览失败');
      }
    } finally {
      setPreviewing(false);
    }
  };

  return (
    <Row gutter={24}>
      <Col xs={24} lg={11}>
        <Card size="small" title="分段设置">
          <ChunkRuleForm
            value={rule}
            onChange={onRuleChange}
            lockedMode={dataset.chunk_mode}
            maxInputTokens={maxInputTokens}
            lastRule={dataset.last_process_rule}
          />
        </Card>
      </Col>
      <Col xs={24} lg={13}>
        <Card size="small" title="分段预览">
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space wrap>
              <Select
                aria-label="预览文件"
                style={{ minWidth: 260 }}
                value={activeId}
                onChange={setSelectedId}
                options={files.map((f) => ({
                  value: f.uploadFileId,
                  label: f.file.name,
                }))}
              />
              <Button
                type="primary"
                disabled={!valid}
                loading={previewing}
                onClick={() => void runPreview()}
              >
                预览
              </Button>
            </Space>
            {!valid && (
              <Alert type="warning" showIcon message="分段设置有误，请先修正后再预览和提交" />
            )}
            {activeBlock && (
              <Alert type="error" showIcon message={`该文件不能提交：${activeBlock.message}`} />
            )}
            {previewError && <Alert type="error" showIcon message={previewError} />}
            {stale && <Alert type="info" showIcon message="分段设置已修改，请重新预览" />}
            {preview && preview.fileId === activeId && <PreviewPanel result={preview.data} />}
          </Space>
        </Card>
      </Col>
      <Col span={24} style={{ marginTop: 16 }}>
        <Space>
          <Button onClick={onBack} disabled={submitting}>
            上一步
          </Button>
          <Button
            type="primary"
            loading={submitting}
            disabled={!valid || submittable.length === 0}
            onClick={onSubmit}
          >
            保存并处理（{submittable.length} 个文件）
          </Button>
          {files.length - submittable.length > 0 && (
            <span style={{ color: '#cf1322' }}>
              {files.length - submittable.length} 个文件因无法解析/超长将不会提交
            </span>
          )}
        </Space>
      </Col>
    </Row>
  );
}
