import { useQuery } from '@tanstack/react-query';
import { ModalForm } from '@ant-design/pro-components';
import { Alert, App, DatePicker, Form, Input, InputNumber, Radio } from 'antd';
import { useMemo, useState } from 'react';
import DatasetOptionSelect from '@/components/DatasetOptionSelect';
import { apiKeyApi } from '@/services/open';
import type { ApiKeyItem, ApiKeySecretResult } from '@/services/types/open-contract';
import { notifyError } from '@/utils/notify';
import {
  DATASET_MAX,
  DESC_MAX,
  NAME_MAX,
  RATE_MAX,
  RATE_MIN,
  SCOPE_LABEL,
  buildKeyBody,
  defaultFormValues,
  formValuesFromItem,
  isAdminDisabledError,
  isExpireDateDisabled,
  mapSubmitError,
  outOfRangeIds,
  validateIpText,
  validateRate,
  validateScope,
  type KeyFormValues,
} from '../logic';

interface Props {
  /** 传入则为编辑，否则为新建 */
  item?: ApiKeyItem;
  onClose: () => void;
  /** 新建成功时携带一次性明文 */
  onSaved: (result: ApiKeySecretResult | null) => void;
}

/** 新建 / 编辑 API 密钥 */
export default function ApiKeyFormModal({ item, onClose, onSaved }: Props) {
  const { message } = App.useApp();
  const [form] = Form.useForm<KeyFormValues>();
  const [staleIds, setStaleIds] = useState<number[]>([]);
  const scope = Form.useWatch('scope_type', form) ?? item?.scope_type ?? 'all';
  const expireMode =
    Form.useWatch('expire_mode', form) ?? (item && !item.expires_at ? 'never' : 'date');
  const initial = useMemo(() => (item ? formValuesFromItem(item) : defaultFormValues()), [item]);

  // 编辑指定范围时，用"当前可检索名单"回显名称，名单外的已选项标记为不可访问
  const accessible = useQuery({
    queryKey: ['open-key-accessible', item?.id],
    queryFn: () => apiKeyApi.accessibleDatasets(item!.id),
    enabled: !!item && item.scope_type === 'selected',
    gcTime: 0,
  });
  const knownLabels = useMemo(
    () => Object.fromEntries((accessible.data ?? []).map((d) => [d.id, d.name])),
    [accessible.data],
  );
  const accessibleIds = useMemo(
    () => new Set((accessible.data ?? []).map((d) => d.id)),
    [accessible.data],
  );
  const isStale = (id: number) =>
    staleIds.includes(id) || (!!item && accessible.isSuccess && !accessibleIds.has(id));

  return (
    <ModalForm<KeyFormValues>
      open
      form={form}
      name="api_key_form"
      title={item ? `编辑 API 密钥「${item.name}」` : '新建 API 密钥'}
      width={600}
      layout="vertical"
      initialValues={initial}
      modalProps={{ destroyOnClose: true, maskClosable: false, onCancel: onClose }}
      submitter={{ searchConfig: { submitText: item ? '保存' : '创建' } }}
      onFinish={async (values) => {
        const body = buildKeyBody(values);
        try {
          if (item) {
            await apiKeyApi.update(item.id, { ...body, version: item.version });
            void message.success('已保存');
            onSaved(null);
          } else {
            const res = await apiKeyApi.create(body);
            onSaved(res);
          }
          return true;
        } catch (err) {
          const bad = outOfRangeIds(err);
          if (bad.length > 0) setStaleIds(bad);
          if (isAdminDisabledError(err)) {
            notifyError(err);
            onSaved(null); // 已被管理员停用：关闭弹窗并刷新列表
            return true;
          }
          const fields = mapSubmitError(err);
          if (fields) {
            form.setFields(
              fields.map((f) => ({ name: f.field as keyof KeyFormValues, errors: [f.message] })),
            );
          } else {
            notifyError(err);
          }
          return false;
        }
      }}
    >
      {item?.stored_status === 'admin_disabled' && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="该密钥已被管理员停用，修改后仍不能自行启用。"
        />
      )}
      <Form.Item
        name="name"
        label="名称"
        rules={[
          { required: true, whitespace: true, message: '请输入名称' },
          { max: NAME_MAX, message: `名称不能超过 ${NAME_MAX} 个字` },
        ]}
        extra="同一账号名下不能重名"
      >
        <Input maxLength={NAME_MAX + 10} placeholder="如：客服系统" />
      </Form.Item>
      <Form.Item
        name="description"
        label="用途说明"
        rules={[{ max: DESC_MAX, message: `不能超过 ${DESC_MAX} 个字` }]}
      >
        <Input.TextArea rows={2} placeholder="选填" />
      </Form.Item>
      <Form.Item name="scope_type" label="检索范围">
        <Radio.Group
          options={[
            { label: SCOPE_LABEL.all, value: 'all' },
            { label: SCOPE_LABEL.selected, value: 'selected' },
          ]}
        />
      </Form.Item>
      {scope === 'selected' ? (
        <Form.Item
          name="dataset_ids"
          label={`选择知识库（1~${DATASET_MAX} 个）`}
          extra="只能从您当前有权访问的知识库中选择；之后失去访问权的知识库会自动不可检索"
          rules={[
            {
              validator: async (_, v: number[] | undefined) => {
                const msg = validateScope('selected', v);
                if (msg) throw new Error(msg);
              },
            },
          ]}
        >
          <DatasetOptionSelect multiple knownLabels={knownLabels} isStale={isStale} />
        </Form.Item>
      ) : (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="全部可访问：之后新获得访问权的知识库自动纳入。"
        />
      )}
      <Form.Item name="expire_mode" label="过期时间">
        <Radio.Group
          options={[
            { label: '指定日期', value: 'date' },
            { label: '永不过期', value: 'never' },
          ]}
        />
      </Form.Item>
      {expireMode === 'date' && (
        <Form.Item
          name="expires_date"
          extra="到期当天 23:59:59 失效，默认一年后"
          rules={[{ required: true, message: '请选择过期日期' }]}
        >
          <DatePicker
            allowClear={false}
            disabledDate={(d) => isExpireDateDisabled(d)}
            style={{ width: '100%' }}
          />
        </Form.Item>
      )}
      <Form.Item
        name="ip_text"
        label="IP 白名单"
        extra="选填，每行一条，最多 20 条，支持 IPv4 与网段（如 10.0.0.0/24）；留空表示不限制"
        rules={[
          {
            validator: async (_, v: string | undefined) => {
              const msg = validateIpText(v);
              if (msg) throw new Error(msg);
            },
          },
        ]}
      >
        <Input.TextArea rows={3} placeholder={'10.0.0.8\n192.168.1.0/24'} />
      </Form.Item>
      <Form.Item
        name="rate_limit_per_min"
        label="每分钟调用上限"
        rules={[
          {
            validator: async (_, v: number | null | undefined) => {
              const msg = validateRate(v);
              if (msg) throw new Error(msg);
            },
          },
        ]}
        extra={`${RATE_MIN}~${RATE_MAX} 次，默认 60`}
      >
        <InputNumber
          min={RATE_MIN}
          max={RATE_MAX}
          precision={0}
          style={{ width: 160 }}
          addonAfter="次/分钟"
        />
      </Form.Item>
    </ModalForm>
  );
}
