import { useQuery, useQueryClient } from '@tanstack/react-query';
import { App, Button, Card } from 'antd';
import { useState } from 'react';
import RetrievalConfigForm from '@/components/RetrievalConfigForm';
import { normalizeRetrievalConfig, validateRetrievalConfig } from '@/components/retrievalConfig';
import { datasetApi, modelApi } from '@/services/kb';
import type { DatasetDetail, RetrievalConfig } from '@/services/types/kb-contract';
import { notifyError } from '@/utils/notify';
import { datasetDetailKey } from '../../useDataset';
import { isVersionConflict, type VersionGuard } from '../logic';

export default function RetrievalSection({
  dataset,
  guard,
}: {
  dataset: DatasetDetail;
  guard: VersionGuard;
}) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [value, setValue] = useState<RetrievalConfig>(dataset.retrieval_config);
  const [saving, setSaving] = useState(false);
  const { data: rerankModels, isLoading } = useQuery({
    queryKey: ['kb-model-options', 'rerank'],
    queryFn: () => modelApi.options('rerank'),
  });
  const models = rerankModels ?? [];
  const errors = validateRetrievalConfig(value, models);
  const invalid = Object.keys(errors).length > 0;

  const save = async () => {
    if (invalid) return;
    setSaving(true);
    try {
      const normalized = normalizeRetrievalConfig(value);
      await datasetApi.updateRetrievalConfig(dataset.id, {
        retrieval_config: normalized,
        version: guard.version,
      });
      setValue(normalized);
      void message.success('检索设置已保存');
      // 接口未返回新详情：重新拉取以取得最新 version（用于后续保存）
      const fresh = await datasetApi.detail(dataset.id);
      qc.setQueryData(datasetDetailKey(dataset.id), fresh);
      guard.onSaved(fresh.version);
    } catch (err) {
      if (isVersionConflict(err)) {
        guard.onConflict();
      } else {
        notifyError(err);
        void qc.invalidateQueries({ queryKey: datasetDetailKey(dataset.id) });
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="检索设置" size="small">
      <div style={{ maxWidth: 560 }}>
        <RetrievalConfigForm
          value={value}
          onChange={setValue}
          rerankModels={models}
          rerankLoading={isLoading}
          errors={errors}
        />
        <Button type="primary" loading={saving} disabled={invalid} onClick={() => void save()}>
          保存检索设置
        </Button>
      </div>
    </Card>
  );
}
