import { CheckCircleFilled, CloseCircleFilled } from '@ant-design/icons';
import {
  ModalForm,
  ProFormDigit,
  ProFormRadio,
  ProFormSwitch,
  ProFormText,
} from '@ant-design/pro-components';
import { Alert, App, Button, Checkbox, Form, Space, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { modelApi } from '@/services/kb';
import { KbErrorCode, type ModelItem } from '@/services/types/kb-contract';
import { isApiError } from '@/utils/error';
import { notifyError } from '@/utils/notify';
import {
  MODEL_EXAMPLES,
  MODEL_TYPE_LABEL,
  buildCreateRequest,
  buildTestRequest,
  buildUpdateRequest,
  canChooseEnabled,
  HIGH_DIMENSION_HINT,
  describeInUse,
  effectiveTestState,
  isConnectionLocked,
  isHighDimension,
  isHttpUrl,
  isInUseData,
  testFingerprint,
  toTestState,
  type ModelFormValues,
  type TestState,
} from '../logic';

interface Props {
  editing?: ModelItem;
  onClose: () => void;
  onSuccess: () => void;
}

export default function ModelFormModal({ editing, onClose, onSuccess }: Props) {
  const [form] = Form.useForm<ModelFormValues>();
  const { message, modal } = App.useApp();
  const [test, setTest] = useState<TestState>({ phase: 'idle' });

  const modelType = (Form.useWatch('model_type', form) ?? editing?.model_type ?? 'embedding') as
    'embedding' | 'rerank';
  const baseUrl = Form.useWatch('base_url', form) ?? editing?.base_url ?? '';
  const modelName = Form.useWatch('model_name', form) ?? editing?.model_name ?? '';
  const apiKey = Form.useWatch('api_key', form);
  const status = Form.useWatch('status', form);
  const dimension = Form.useWatch('dimension', form);
  const locked = isConnectionLocked(editing);

  const fingerprint = testFingerprint({
    model_type: modelType,
    base_url: baseUrl,
    model_name: modelName,
    api_key: apiKey,
  });
  const savedFingerprint = useMemo(
    () =>
      editing
        ? testFingerprint({
            model_type: editing.model_type,
            base_url: editing.base_url,
            model_name: editing.model_name,
          })
        : undefined,
    [editing],
  );
  const current = effectiveTestState(test, fingerprint);
  const highDimension =
    modelType === 'embedding' &&
    isHighDimension(dimension, current.phase === 'success' ? current.result.dimension : null);
  const enableAllowed = canChooseEnabled(test, fingerprint, editing, savedFingerprint);

  const runTest = async () => {
    try {
      await form.validateFields(['base_url', 'model_name']);
    } catch {
      return;
    }
    const v = form.getFieldsValue();
    const fp = testFingerprint({
      model_type: modelType,
      base_url: v.base_url,
      model_name: v.model_name,
      api_key: v.api_key,
    });
    setTest({ phase: 'testing' });
    try {
      const result = await modelApi.test(
        buildTestRequest({ ...v, model_type: modelType }, editing),
      );
      setTest(toTestState(fp, result));
      if (result.success && modelType === 'embedding' && result.dimension && !locked) {
        form.setFieldValue('dimension', result.dimension);
      }
      if (!result.success && form.getFieldValue('status') === 'enabled') {
        form.setFieldValue('status', 'disabled');
      }
    } catch (err) {
      setTest({ phase: 'idle' });
      notifyError(err);
    }
  };

  const handleValuesChange = (changed: Partial<ModelFormValues>) => {
    // 连接信息变化后测试结果作废：已选“启用”则退回“停用”
    if (
      ('base_url' in changed || 'model_name' in changed || 'api_key' in changed) &&
      form.getFieldValue('status') === 'enabled'
    ) {
      const v = form.getFieldsValue();
      const fp = testFingerprint({
        model_type: modelType,
        base_url: v.base_url,
        model_name: v.model_name,
        api_key: v.api_key,
      });
      if (!canChooseEnabled(test, fp, editing, savedFingerprint)) {
        form.setFieldValue('status', 'disabled');
        form.setFieldValue('is_default', false);
      }
    }
  };

  const handleError = (err: unknown) => {
    if (isApiError(err)) {
      if (err.code === KbErrorCode.MODEL_NAME_EXISTS) {
        form.setFields([{ name: 'name', errors: [err.message] }]);
        return;
      }
      if (err.code === KbErrorCode.MODEL_DIMENSION_REQUIRED) {
        form.setFields([{ name: 'dimension', errors: [err.message] }]);
        return;
      }
      if (err.code === KbErrorCode.MODEL_IN_USE_MODIFY && isInUseData(err.data)) {
        modal.error({
          title: err.message,
          content: `引用的知识库：${describeInUse(err.data)}`,
        });
        return;
      }
      if (err.code === KbErrorCode.MODEL_TEST_FAILED) {
        const data = err.data as { error_message?: string } | null;
        const reason = data?.error_message;
        setTest({
          phase: 'failed',
          fingerprint,
          message: reason || err.message,
        });
        form.setFieldValue('status', 'disabled');
        void message.error(reason ? `${err.message}：${reason}` : err.message);
        return;
      }
    }
    notifyError(err);
  };

  const handleFinish = async (v: ModelFormValues): Promise<boolean> => {
    try {
      if (editing) {
        await modelApi.update(editing.id, buildUpdateRequest(v, editing));
      } else {
        await modelApi.create(buildCreateRequest(v));
      }
    } catch (err) {
      handleError(err);
      return false;
    }
    void message.success(editing ? '保存成功' : '新增成功');
    onSuccess();
    return true;
  };

  const example = MODEL_EXAMPLES[modelType];

  return (
    <ModalForm<ModelFormValues>
      title={editing ? `编辑模型：${editing.name}` : '新增模型'}
      open
      form={form}
      width={600}
      layout="vertical"
      modalProps={{ destroyOnClose: true, maskClosable: false, onCancel: onClose }}
      initialValues={
        editing
          ? {
              name: editing.name,
              model_type: editing.model_type,
              base_url: editing.base_url,
              model_name: editing.model_name,
              dimension: editing.dimension ?? undefined,
              max_input_tokens: editing.max_input_tokens,
              status: editing.status,
              is_default: editing.is_default,
            }
          : {
              model_type: 'embedding',
              max_input_tokens: 512,
              status: 'disabled',
              is_default: false,
            }
      }
      onValuesChange={handleValuesChange}
      onFinish={handleFinish}
    >
      {locked && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`该模型已被 ${editing?.dataset_count} 个知识库使用，服务地址、模型标识和向量维度不能修改，只能停用。`}
        />
      )}
      <ProFormText
        name="name"
        label="显示名称"
        fieldProps={{ maxLength: 50 }}
        rules={[{ required: true, whitespace: true, message: '请输入显示名称（1~50 字）' }]}
      />
      <ProFormRadio.Group
        name="model_type"
        label="模型类型"
        disabled={!!editing}
        options={Object.entries(MODEL_TYPE_LABEL).map(([value, label]) => ({ value, label }))}
        fieldProps={{
          onChange: () => {
            setTest({ phase: 'idle' });
            form.setFieldValue('status', 'disabled');
            form.setFieldValue('is_default', false);
          },
        }}
      />
      <ProFormText
        name="base_url"
        label="服务地址"
        disabled={locked}
        placeholder="如：http://10.0.0.5:9997/v1（OpenAI 兼容接口）"
        fieldProps={{ maxLength: 500 }}
        rules={[
          { required: true, whitespace: true, message: '请输入服务地址' },
          {
            validator: (_, value: string | undefined) =>
              !value || isHttpUrl(value)
                ? Promise.resolve()
                : Promise.reject(new Error('服务地址必须以 http:// 或 https:// 开头')),
          },
        ]}
      />
      <ProFormText
        name="model_name"
        label="模型标识"
        disabled={locked}
        placeholder="如：bge-m3 / bge-reranker-v2-m3"
        extra={`推荐示例：${example.model_name}${
          example.dimension
            ? `（维度 ${example.dimension}，最大输入 ${example.max_input_tokens} tokens）`
            : ''
        }`}
        fieldProps={{ maxLength: 100 }}
        rules={[{ required: true, whitespace: true, message: '请输入模型标识' }]}
      />
      <ProFormText.Password
        name="api_key"
        label="访问凭据"
        placeholder={editing?.api_key_hint ? `${editing.api_key_hint}（留空表示不修改）` : '可选'}
        fieldProps={{ maxLength: 500, autoComplete: 'new-password' }}
        extra={
          editing?.api_key_hint ? (
            <Form.Item name="clear_api_key" valuePropName="checked" noStyle>
              <Checkbox disabled={!!apiKey}>清空已保存的凭据</Checkbox>
            </Form.Item>
          ) : undefined
        }
      />
      {modelType === 'embedding' && (
        <ProFormDigit
          name="dimension"
          label="向量维度"
          disabled={locked}
          min={1}
          max={16000}
          fieldProps={{ precision: 0 }}
          placeholder="可通过“测试连接”自动获取"
          rules={[{ required: true, message: '请填写向量维度，或通过“测试连接”自动获取' }]}
        />
      )}
      {highDimension && (
        <Alert type="warning" showIcon style={{ marginBottom: 16 }} message={HIGH_DIMENSION_HINT} />
      )}
      <ProFormDigit
        name="max_input_tokens"
        label="单次最大输入长度（tokens）"
        min={1}
        max={131072}
        fieldProps={{ precision: 0 }}
        rules={[{ required: true, message: '请填写单次最大输入长度（1~131072）' }]}
      />
      <Form.Item label="连接测试" extra="保存前请测试连接；测试未通过的模型只能保存为停用。">
        <Space direction="vertical" size={4}>
          <Button onClick={runTest} loading={current.phase === 'testing'}>
            测试连接
          </Button>
          {current.phase === 'success' && (
            <Typography.Text type="success">
              <CheckCircleFilled /> 连接成功
              {current.result.dimension ? `，向量维度 ${current.result.dimension}` : ''}
              {current.result.latency_ms != null ? `，耗时 ${current.result.latency_ms} ms` : ''}
            </Typography.Text>
          )}
          {current.phase === 'failed' && (
            <Typography.Text type="danger">
              <CloseCircleFilled /> 测试未通过：{current.message}
            </Typography.Text>
          )}
        </Space>
      </Form.Item>
      <ProFormRadio.Group
        name="status"
        label="状态"
        options={[
          { value: 'enabled', label: '启用', disabled: !enableAllowed },
          { value: 'disabled', label: '停用' },
        ]}
        extra={!enableAllowed ? '请先“测试连接”并通过后才能启用' : undefined}
        fieldProps={{
          onChange: (e) => {
            if (e.target.value !== 'enabled') form.setFieldValue('is_default', false);
          },
        }}
      />
      <ProFormSwitch
        name="is_default"
        label="设为默认模型"
        disabled={status !== 'enabled'}
        extra="每种类型最多一个默认模型，新建知识库时默认选中；仅启用状态可设为默认。"
      />
    </ModalForm>
  );
}
