import { ModalForm, ProFormDigit, ProFormRadio, ProFormText } from '@ant-design/pro-components';
import { Form } from 'antd';
import { App } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import OrgTreeSelect from '@/components/OrgTreeSelect';
import UserSelect from '@/components/UserSelect';
import { ORG_OPTIONS_KEY, useOrgOptions } from '@/hooks/useOrgOptions';
import { orgApi } from '@/services/iam';
import type { EnableStatus, OrgNode, OrgType } from '@/services/types/iam-contract';
import { ORG_TYPE_LABEL, allowedChildTypes, findNode } from '@/utils/orgTree';
import { notifyError } from '@/utils/notify';

interface FormValues {
  parent_id?: number;
  org_type?: Exclude<OrgType, 'group'>;
  name: string;
  code: string;
  leader_user_id?: number | null;
  sort_order?: number;
  status?: EnableStatus;
}

interface Props {
  /** 编辑时传入；新增时不传 */
  editing?: OrgNode;
  /** 新增下级时固定上级；不传则可在表单内选择 */
  parent?: { id: number; org_type: OrgType; name: string };
  onClose: () => void;
  onSuccess: () => void;
}

export default function OrgFormModal({ editing, parent, onClose, onSuccess }: Props) {
  const [form] = Form.useForm<FormValues>();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { data: options } = useOrgOptions();
  const parentIdValue = Form.useWatch('parent_id', form);

  const parentType: OrgType | undefined = parent
    ? parent.org_type
    : parentIdValue
      ? findNode(options ?? [], parentIdValue)?.org_type
      : undefined;
  const typeOptions = allowedChildTypes(parentType).map((t) => ({
    value: t,
    label: ORG_TYPE_LABEL[t],
  }));

  const handleFinish = async (values: FormValues): Promise<boolean> => {
    try {
      if (editing) {
        await orgApi.update(editing.id, {
          name: values.name.trim(),
          leader_user_id: values.leader_user_id ?? null,
          sort_order: values.sort_order ?? 0,
          version: editing.version,
        });
      } else {
        const parentId = parent?.id ?? values.parent_id;
        if (!parentId || !values.org_type) return false;
        await orgApi.create({
          parent_id: parentId,
          org_type: values.org_type,
          name: values.name.trim(),
          code: values.code.trim(),
          leader_user_id: values.leader_user_id ?? null,
          sort_order: values.sort_order ?? 0,
          status: values.status ?? 'enabled',
        });
      }
    } catch (err) {
      notifyError(err);
      return false;
    }
    void message.success(editing ? '保存成功' : '新增成功');
    void queryClient.invalidateQueries({ queryKey: [ORG_OPTIONS_KEY] });
    onSuccess();
    return true;
  };

  return (
    <ModalForm<FormValues>
      title={editing ? '编辑组织' : parent ? `新增下级组织（上级：${parent.name}）` : '新增组织'}
      open
      form={form}
      width={520}
      layout="vertical"
      modalProps={{ destroyOnClose: true, maskClosable: false, onCancel: onClose }}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      initialValues={
        editing
          ? {
              name: editing.name,
              code: editing.code,
              leader_user_id: editing.leader_user_id,
              sort_order: editing.sort_order,
            }
          : { sort_order: 0, status: 'enabled', org_type: typeOptions[0]?.value }
      }
      onFinish={handleFinish}
    >
      {!editing && !parent && (
        <Form.Item
          name="parent_id"
          label="上级组织"
          rules={[{ required: true, message: '请选择上级组织' }]}
        >
          <OrgTreeSelect
            allowClear={false}
            disableUnmanageable
            onChange={() => form.setFieldValue('org_type', undefined)}
          />
        </Form.Item>
      )}
      {!editing && (
        <ProFormRadio.Group
          name="org_type"
          label="组织类型"
          options={typeOptions}
          rules={[{ required: true, message: '请选择组织类型' }]}
          extra={typeOptions.length === 0 ? '请先选择上级组织' : undefined}
        />
      )}
      <ProFormText
        name="name"
        label="组织名称"
        fieldProps={{ maxLength: 50 }}
        rules={[{ required: true, whitespace: true, message: '请输入组织名称（1~50 字）' }]}
      />
      <ProFormText
        name="code"
        label="组织编码"
        disabled={!!editing}
        fieldProps={{ maxLength: 32 }}
        extra={editing ? '编码创建后不可修改' : undefined}
        rules={[
          { required: true, message: '请输入组织编码' },
          { pattern: /^[A-Za-z0-9_-]{1,32}$/, message: '仅限字母、数字、下划线、中划线，1~32 位' },
        ]}
      />
      <Form.Item name="leader_user_id" label="负责人">
        <UserSelect initialLabel={editing?.leader_name} />
      </Form.Item>
      <ProFormDigit
        name="sort_order"
        label="显示顺序"
        min={0}
        max={9999}
        fieldProps={{ precision: 0 }}
        rules={[{ required: true, message: '请输入显示顺序' }]}
      />
      {!editing && (
        <ProFormRadio.Group
          name="status"
          label="状态"
          options={[
            { value: 'enabled', label: '启用' },
            { value: 'disabled', label: '停用' },
          ]}
        />
      )}
    </ModalForm>
  );
}
