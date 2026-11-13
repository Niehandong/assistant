import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, App, Button, Card, Form, Input, Radio, Select, Typography } from 'antd';
import { useState } from 'react';
import DatasetIcon from '@/components/DatasetIcon';
import { DATASET_ICONS, DEFAULT_DATASET_ICON } from '@/components/datasetIcons';
import { datasetApi, modelApi } from '@/services/kb';
import { KbErrorCode, type DatasetDetail } from '@/services/types/kb-contract';
import { isApiError } from '@/utils/error';
import { notifyError } from '@/utils/notify';
import { CHUNK_MODE_UNSET_TEXT, CHUNK_MODE_LABEL } from '../../../list/logic';
import { datasetDetailKey } from '../../useDataset';
import { embeddingModelState, isVersionConflict, type VersionGuard } from '../logic';

interface Values {
  name: string;
  description?: string;
  icon?: string;
  embedding_model_id?: number;
}

export default function BasicInfoForm({
  dataset,
  guard,
}: {
  dataset: DatasetDetail;
  guard: VersionGuard;
}) {
  const [form] = Form.useForm<Values>();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [saving, setSaving] = useState(false);
  const isOwner = dataset.my_permission === 'owner';
  const { data: models } = useQuery({
    queryKey: ['kb-model-options', 'embedding'],
    queryFn: () => modelApi.options('embedding'),
  });
  const modelState = embeddingModelState(dataset, isOwner);

  // 当前模型可能已停用（不在启用选项里），仍需回显
  const options = [
    ...(models ?? []).map((m) => ({
      value: m.id,
      label: `${m.name}${m.is_default ? '（默认）' : ''}`,
    })),
  ];
  if (!options.some((o) => o.value === dataset.embedding_model.id)) {
    options.unshift({
      value: dataset.embedding_model.id,
      label: `${dataset.embedding_model.name}（已停用）`,
    });
  }

  const submit = async (v: Values) => {
    setSaving(true);
    try {
      const updated = await datasetApi.update(dataset.id, {
        name: v.name.trim(),
        description: v.description?.trim() || null,
        icon: v.icon || DEFAULT_DATASET_ICON,
        ...(v.embedding_model_id && v.embedding_model_id !== dataset.embedding_model.id
          ? { embedding_model_id: v.embedding_model_id }
          : {}),
        version: guard.version,
      });
      guard.onSaved(updated.version);
      qc.setQueryData(datasetDetailKey(dataset.id), updated);
      form.setFieldsValue({
        name: updated.name,
        description: updated.description ?? undefined,
        icon: updated.icon ?? DEFAULT_DATASET_ICON,
        embedding_model_id: updated.embedding_model.id,
      });
      void qc.invalidateQueries({ queryKey: ['kb-datasets'] });
      void message.success('保存成功');
    } catch (err) {
      if (isApiError(err) && err.code === KbErrorCode.DATASET_NAME_EXISTS) {
        form.setFields([{ name: 'name', errors: [err.message] }]);
      } else if (isVersionConflict(err)) {
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
    <Card title="基础信息" size="small">
      <Form<Values>
        form={form}
        layout="vertical"
        style={{ maxWidth: 560 }}
        initialValues={{
          name: dataset.name,
          description: dataset.description ?? undefined,
          icon: dataset.icon ?? DEFAULT_DATASET_ICON,
          embedding_model_id: dataset.embedding_model.id,
        }}
        onFinish={submit}
      >
        <Form.Item
          name="name"
          label="知识库名称"
          rules={[{ required: true, whitespace: true, message: '请输入知识库名称（1~50 字）' }]}
        >
          <Input maxLength={50} showCount />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea maxLength={400} showCount autoSize={{ minRows: 2, maxRows: 5 }} />
        </Form.Item>
        <Form.Item name="icon" label="图标">
          <Radio.Group>
            {Object.keys(DATASET_ICONS).map((key) => (
              <Radio.Button key={key} value={key} aria-label={`图标 ${key}`}>
                <DatasetIcon name={key} />
              </Radio.Button>
            ))}
          </Radio.Group>
        </Form.Item>
        <Form.Item name="embedding_model_id" label="Embedding 模型" extra={modelState.hint}>
          <Select options={options} disabled={modelState.readOnly} aria-label="Embedding 模型" />
        </Form.Item>
        <Form.Item label="分段方式">
          <Typography.Text>
            {dataset.chunk_mode ? CHUNK_MODE_LABEL[dataset.chunk_mode] : CHUNK_MODE_UNSET_TEXT}
          </Typography.Text>
          <div>
            <Typography.Text type="secondary">
              首次上传文档时确定，之后固定；删除全部文档后可重新选择
            </Typography.Text>
          </div>
        </Form.Item>
        {dataset.embedding_model.status === 'disabled' && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="向量模型已停用，请联系管理员"
          />
        )}
        <Button type="primary" htmlType="submit" loading={saving}>
          保存基础信息
        </Button>
      </Form>
    </Card>
  );
}
