import { ModalForm, ProFormSelect, ProFormText, ProFormTextArea } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Alert, App, Form, Radio } from 'antd';
import { useEffect } from 'react';
import DatasetIcon from '@/components/DatasetIcon';
import { DATASET_ICONS, DEFAULT_DATASET_ICON } from '@/components/datasetIcons';
import { datasetApi, modelApi } from '@/services/kb';
import { KbErrorCode, type DatasetDetail } from '@/services/types/kb-contract';
import { isApiError } from '@/utils/error';
import { notifyError } from '@/utils/notify';
import { pickDefaultModelId } from '../logic';

interface FormValues {
  name: string;
  description?: string;
  icon?: string;
  embedding_model_id?: number;
}

interface Props {
  onClose: () => void;
  onCreated: (dataset: DatasetDetail) => void;
}

export default function CreateDatasetModal({ onClose, onCreated }: Props) {
  const [form] = Form.useForm<FormValues>();
  const { message } = App.useApp();
  const {
    data: models,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['kb-model-options', 'embedding'],
    queryFn: () => modelApi.options('embedding'),
  });

  // 模型选项到达后默认选中默认模型（用户已手动选择则不覆盖）
  useEffect(() => {
    if (models && form.getFieldValue('embedding_model_id') === undefined) {
      form.setFieldValue('embedding_model_id', pickDefaultModelId(models));
    }
  }, [models, form]);

  const noModel = !!models && models.length === 0;

  const handleFinish = async (v: FormValues): Promise<boolean> => {
    try {
      const created = await datasetApi.create({
        name: v.name.trim(),
        description: v.description?.trim() || null,
        icon: v.icon || DEFAULT_DATASET_ICON,
        embedding_model_id: v.embedding_model_id,
      });
      void message.success('知识库创建成功');
      onCreated(created);
      return true;
    } catch (err) {
      if (isApiError(err) && err.code === KbErrorCode.DATASET_NAME_EXISTS) {
        form.setFields([{ name: 'name', errors: [err.message] }]);
      } else if (isApiError(err) && err.code === KbErrorCode.MODEL_NOT_ENABLED) {
        form.setFields([{ name: 'embedding_model_id', errors: [err.message] }]);
      } else {
        notifyError(err);
      }
      return false;
    }
  };

  return (
    <ModalForm<FormValues>
      title="创建知识库"
      open
      form={form}
      width={520}
      layout="vertical"
      modalProps={{ destroyOnClose: true, maskClosable: false, onCancel: onClose }}
      initialValues={{ icon: DEFAULT_DATASET_ICON }}
      submitter={{ submitButtonProps: { disabled: noModel } }}
      onFinish={handleFinish}
    >
      <ProFormText
        name="name"
        label="知识库名称"
        fieldProps={{ maxLength: 50, showCount: true }}
        rules={[{ required: true, whitespace: true, message: '请输入知识库名称（1~50 字）' }]}
      />
      <ProFormTextArea
        name="description"
        label="描述"
        fieldProps={{ maxLength: 400, showCount: true, autoSize: { minRows: 2, maxRows: 5 } }}
      />
      <Form.Item name="icon" label="图标">
        <Radio.Group>
          {Object.keys(DATASET_ICONS).map((key) => (
            <Radio.Button key={key} value={key} aria-label={`图标 ${key}`}>
              <DatasetIcon name={key} />
            </Radio.Button>
          ))}
        </Radio.Group>
      </Form.Item>
      {noModel && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="暂无可用的 Embedding 模型，请联系管理员先在“模型配置”中启用"
        />
      )}
      {isError && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message="模型列表加载失败"
          action={<a onClick={() => void refetch()}>重试</a>}
        />
      )}
      <ProFormSelect
        name="embedding_model_id"
        label="Embedding 模型"
        placeholder="请选择向量模型"
        extra="知识库内有文档后不能更换向量模型"
        fieldProps={{
          loading: isLoading,
          options: (models ?? []).map((m) => ({
            value: m.id,
            label: `${m.name}${m.is_default ? '（默认）' : ''}${m.dimension ? ` · ${m.dimension} 维` : ''}`,
          })),
        }}
        rules={[{ required: true, message: '请选择已启用的 Embedding 模型' }]}
      />
    </ModalForm>
  );
}
