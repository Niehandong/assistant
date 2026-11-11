import { ModalForm, ProFormRadio, ProFormText, ProFormTextArea } from '@ant-design/pro-components';
import { App, Form } from 'antd';
import OrgTreeSelect from '@/components/OrgTreeSelect';
import { roleApi } from '@/services/iam';
import type { RoleItem, RoleType } from '@/services/types/iam-contract';
import { submitWithLockoutConfirm } from '@/utils/lockout';
import { notifyError } from '@/utils/notify';

interface FormValues {
  code: string;
  name: string;
  role_type: RoleType;
  owner_company_id?: number;
  status: 'enabled' | 'disabled';
  remark?: string;
}

interface Props {
  editing?: RoleItem;
  onClose: () => void;
  onSuccess: () => void;
}

export default function RoleFormModal({ editing, onClose, onSuccess }: Props) {
  const [form] = Form.useForm<FormValues>();
  const { message, modal } = App.useApp();
  const roleType = Form.useWatch('role_type', form);

  const confirm = (content: string) =>
    new Promise<boolean>((resolve) => {
      modal.confirm({
        title: '保存后您将失去该页面权限',
        content,
        okButtonProps: { danger: true },
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });

  const handleFinish = async (v: FormValues): Promise<boolean> => {
    try {
      if (editing) {
        await submitWithLockoutConfirm(
          (confirmSelfLockout) =>
            roleApi.update(editing.id, {
              name: v.name.trim(),
              status: v.status,
              remark: v.remark?.trim() || null,
              version: editing.version,
              confirm_self_lockout: confirmSelfLockout,
            }),
          confirm,
        );
      } else {
        await roleApi.create({
          code: v.code.trim(),
          name: v.name.trim(),
          role_type: v.role_type,
          owner_company_id: v.role_type === 'company' ? v.owner_company_id : undefined,
          status: v.status,
          remark: v.remark?.trim() || null,
        });
      }
    } catch (err) {
      notifyError(err);
      return false;
    }
    void message.success(editing ? '保存成功' : '新增成功，请继续为角色分配权限');
    onSuccess();
    return true;
  };

  return (
    <ModalForm<FormValues>
      title={editing ? `编辑角色：${editing.name}` : '新增角色'}
      open
      form={form}
      width={520}
      layout="vertical"
      modalProps={{ destroyOnClose: true, maskClosable: false, onCancel: onClose }}
      initialValues={
        editing
          ? {
              code: editing.code,
              name: editing.name,
              role_type: editing.role_type,
              owner_company_id: editing.owner_company_id ?? undefined,
              status: editing.status,
              remark: editing.remark ?? undefined,
            }
          : { role_type: 'company', status: 'enabled' }
      }
      onFinish={handleFinish}
    >
      <ProFormText
        name="code"
        label="角色编码"
        disabled={!!editing}
        fieldProps={{ maxLength: 50 }}
        rules={[
          { required: true, message: '请输入角色编码' },
          { pattern: /^[A-Za-z0-9_]{2,50}$/, message: '仅限字母、数字、下划线，2~50 位' },
        ]}
      />
      <ProFormText
        name="name"
        label="角色名称"
        fieldProps={{ maxLength: 30 }}
        rules={[{ required: true, whitespace: true, message: '请输入角色名称（1~30 字）' }]}
      />
      <ProFormRadio.Group
        name="role_type"
        label="角色类型"
        disabled={!!editing}
        options={[
          { value: 'company', label: '公司级' },
          { value: 'group', label: '集团级' },
        ]}
      />
      {roleType === 'company' && (
        <Form.Item
          name="owner_company_id"
          label="所属公司"
          rules={[{ required: true, message: '公司级角色必须指定所属公司' }]}
        >
          <OrgTreeSelect types="group,company" disabled={!!editing} allowClear={false} />
        </Form.Item>
      )}
      <ProFormRadio.Group
        name="status"
        label="状态"
        options={[
          { value: 'enabled', label: '启用' },
          { value: 'disabled', label: '停用' },
        ]}
      />
      <ProFormTextArea
        name="remark"
        label="备注"
        fieldProps={{ maxLength: 200, showCount: true }}
      />
    </ModalForm>
  );
}
