import { SettingOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Card,
  Drawer,
  Flex,
  Input,
  Result,
  Space,
  Spin,
  Typography,
} from 'antd';
import { useState } from 'react';
import { usePermission } from '@/access/usePermission';
import RetrievalConfigForm from '@/components/RetrievalConfigForm';
import { normalizeRetrievalConfig, validateRetrievalConfig } from '@/components/retrievalConfig';
import { datasetApi, modelApi, retrievalApi } from '@/services/kb';
import type {
  RetrievalConfig,
  RetrievalResult,
  RetrieveHistoryItem,
} from '@/services/types/kb-contract';
import { notifyError } from '@/utils/notify';
import { datasetDetailKey, useDataset } from '../useDataset';
import RecallRecordTable from './components/RecallRecordTable';
import RecallResultList from './components/RecallResultList';
import {
  QUERY_MAX_LENGTH,
  buildTestRequest,
  canSaveAsDefault,
  describeRecallError,
  summarizeConfig,
  testAvailability,
  validateQuery,
} from './logic';

/** 召回测试页（FE-14）：路由 /kb/datasets/:id/recall */
export default function RecallPage() {
  const dataset = useDataset();
  const can = usePermission();
  const qc = useQueryClient();
  const { message } = App.useApp();

  const [query, setQuery] = useState('');
  const [config, setConfig] = useState<RetrievalConfig>(dataset.retrieval_config);
  const [draft, setDraft] = useState<RetrievalConfig | null>(null);
  const [result, setResult] = useState<RetrievalResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const records = useQuery({
    queryKey: ['kb-recall-records', dataset.id],
    queryFn: () => retrievalApi.records(dataset.id),
    enabled: can('kb:retrieval:test'),
  });
  const rerank = useQuery({
    queryKey: ['kb-model-options', 'rerank'],
    queryFn: () => modelApi.options('rerank'),
    enabled: can('kb:retrieval:test'),
  });
  const rerankModels = rerank.data ?? [];

  const availability = testAvailability(dataset);
  const queryError = query === '' ? null : validateQuery(query);

  const test = useMutation({
    mutationFn: (p: { q: string; cfg: RetrievalConfig }) =>
      retrievalApi.test(dataset.id, buildTestRequest(p.q, p.cfg, dataset.retrieval_config)),
    onSuccess: (r) => {
      setResult(r);
      setError(null);
    },
    onError: (err) => {
      // 模型/服务异常：展示错误，不显示空结果
      setResult(null);
      setError(describeRecallError(err));
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ['kb-recall-records', dataset.id] }),
  });

  if (!can('kb:retrieval:test')) {
    return <Result status="403" title="您没有召回测试的权限" />;
  }

  const run = (q: string, cfg: RetrievalConfig) => {
    if (validateQuery(q) || !availability.enabled) return;
    test.mutate({ q, cfg });
  };

  const retest = (r: RetrieveHistoryItem) => {
    setQuery(r.query);
    setConfig(r.retrieval_config);
    run(r.query, r.retrieval_config);
  };

  const draftErrors = draft ? validateRetrievalConfig(draft, rerankModels) : {};
  const draftInvalid = Object.keys(draftErrors).length > 0;
  const showSaveDefault = canSaveAsDefault(dataset.my_permission, can);
  const rerankId = config.reranking_model_id;
  const rerankName = rerankModels.find((m) => m.id === rerankId)?.name ?? null;

  const saveDefault = async () => {
    if (!draft || draftInvalid) return;
    const normalized = normalizeRetrievalConfig(draft);
    try {
      await datasetApi.updateRetrievalConfig(dataset.id, {
        retrieval_config: normalized,
        version: dataset.version,
      });
      void message.success('已保存为知识库默认设置');
      setConfig(normalized);
      setDraft(null);
      await qc.invalidateQueries({ queryKey: datasetDetailKey(dataset.id) });
    } catch (err) {
      notifyError(err);
      void qc.invalidateQueries({ queryKey: datasetDetailKey(dataset.id) });
    }
  };

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card size="small" title="召回测试">
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <div>
            <Input.TextArea
              aria-label="测试问题"
              rows={4}
              placeholder="输入要测试的问题"
              value={query}
              status={queryError ? 'error' : undefined}
              onChange={(e) => setQuery(e.target.value)}
            />
            <Flex justify="space-between" style={{ marginTop: 4 }}>
              <Typography.Text type="danger">{queryError}</Typography.Text>
              <Typography.Text
                type={query.trim().length > QUERY_MAX_LENGTH ? 'danger' : 'secondary'}
              >
                {query.trim().length}/{QUERY_MAX_LENGTH}
              </Typography.Text>
            </Flex>
          </div>
          <Flex justify="space-between" align="center" wrap="wrap" gap={8}>
            <Space size={8} wrap>
              <Typography.Text type="secondary" data-testid="config-summary">
                {summarizeConfig(config, rerankName)}
              </Typography.Text>
              <Button size="small" icon={<SettingOutlined />} onClick={() => setDraft(config)}>
                修改
              </Button>
            </Space>
            <Button
              type="primary"
              loading={test.isPending}
              disabled={!availability.enabled || query.trim() === '' || !!validateQuery(query)}
              onClick={() => run(query, config)}
            >
              测试
            </Button>
          </Flex>
          {availability.reason && <Alert type="warning" showIcon message={availability.reason} />}
        </Space>
      </Card>

      {(test.isPending || result || error) && (
        <Card size="small" title="召回结果">
          {test.isPending ? (
            <Flex justify="center" style={{ padding: 32 }}>
              <Spin />
              <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                检索中…
              </Typography.Text>
            </Flex>
          ) : error ? (
            <Alert type="error" showIcon message="召回测试失败" description={error} />
          ) : result ? (
            <RecallResultList result={result} />
          ) : null}
        </Card>
      )}

      <RecallRecordTable
        records={records.data}
        loading={records.isLoading}
        error={records.error}
        disabled={!availability.enabled || test.isPending}
        onRetry={() => void records.refetch()}
        onRetest={retest}
      />

      <Drawer
        title="检索设置"
        open={!!draft}
        width={480}
        onClose={() => setDraft(null)}
        destroyOnClose
        footer={
          <Space>
            <Button
              type="primary"
              disabled={draftInvalid}
              onClick={() => {
                if (draft) setConfig(normalizeRetrievalConfig(draft));
                setDraft(null);
              }}
            >
              应用（仅本次测试）
            </Button>
            {showSaveDefault && (
              <Button disabled={draftInvalid} onClick={() => void saveDefault()}>
                保存为默认设置
              </Button>
            )}
            <Button onClick={() => setDraft(null)}>取消</Button>
          </Space>
        }
      >
        {draft && (
          <RetrievalConfigForm
            value={draft}
            onChange={setDraft}
            rerankModels={rerankModels}
            rerankLoading={rerank.isLoading}
            errors={draftErrors}
          />
        )}
      </Drawer>
    </Space>
  );
}
