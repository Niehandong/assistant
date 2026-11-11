import { ModalForm, ProFormSwitch, ProFormText } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { App, Form, Select } from 'antd';
import OrgTreeSelect from '@/components/OrgTreeSelect';
import { roleApi, userApi } from '@/services/iam';
import type { UserCreateResult, UserItem } from '@/services/types/iam-contract';
import { notifyError } from '@/utils/notify';

interface FormValues {
  username: string;
  name: string;
  org_id: number;
  mobile?: string;
  email?: string;
  auto_password?: boolean;
  password?: string;
  role_ids?: number[];
}

interface Props {
  editing?: UserItem;
  onClose: () => void;
  onCreated: (result: UserCreateResult) => void;
  onUpdated: () => void;
}

export default function UserFormModal({ editing, onClose, onCreated, onUpdated }: Props) {
  const [form] = Form.useForm<FormValues>();
  const { message } = App.useApp();
  const autoPassword = Form.useWatch('auto_password', form);
  const orgId = Form.useWatch('org_id', form);
  // 新增时：选定组织后按 org_id 拉取可分配角色（契约 5.4.2）
  const roles = useQuery({
    queryKey: ['assignable-roles-by-org', orgId],
    queryFn: () => roleApi.assignable({ org_id: orgId as number }),
    enabled: !editing && !!orgId,
    gcTime: 0,
  });

  const handleFinish = async (v: FormValues): Promise<boolean> => {
    const mobile = v.mobile?.trim() || null;
    const email = v.email?.trim() || null;
    try {
      if (editing) {
        await userApi.update(editing.id, {
          name: v.name.trim(),
          org_id: v.org_id,
          mobile,
          email,
          version: editing.version,
        });
        void message.success('保存成功');
        onUpdated();
      } else {
        const result = await userApi.create({
          username: v.username.trim(),
          name: v.name.trim(),
          org_id: v.org_id,
          mobile,
          email,
          password: v.auto_password ? undefined : v.password,
          role_ids: v.role_ids ?? [],
        });
        void message.success('新增成功');
        onCreated(result);
      }
      return true;
    } catch (err) {
      notifyError(err);
      return false;
    }
  };

  return (
    <ModalForm<FormValues>
      title={editing ? '编辑用户' : '新增用户'}
      open
      form={form}
      width={520}
      layout="vertical"
      modalProps={{ destroyOnClose: true, maskClosable: false, onCancel: onClose }}
      initialValues={
        editing
          ? {
              username: editing.username,
              name: editing.name,
              org_id: editing.org_id,
              mobile: editing.mobile ?? undefined,
              email: editing.email ?? undefined,
            }
          : { auto_password: true }
      }
      onFinish={handleFinish}
    >
      <ProFormText
        name="username"
        label="账号"
        disabled={!!editing}
        extra={editing ? '账号创建后不可修改' : '字母开头，4~32 位字母、数字或下划线'}
        fieldProps={{ maxLength: 32 }}
        rules={[
          { required: true, message: '请输入账号' },
          {
            pattern: /^[A-Za-z][A-Za-z0-9_]{3,31}$/,
            message: '字母开头，4~32 位字母、数字或下划线',
          },
        ]}
      />
      <ProFormText
        name="name"
        label="姓名"
        fieldProps={{ maxLength: 30 }}
        rules={[{ required: true, whitespace: true, message: '请输入姓名（1~30 字）' }]}
      />
      <Form.Item
        name="org_id"
        label="所属组织"
        rules={[{ required: true, message: '请选择所属组织' }]}
      >
        <OrgTreeSelect
          allowClear={false}
          disableUnmanageable
          onChange={() => form.setFieldValue('role_ids', [])}
        />
      </Form.Item>
      <ProFormText
        name="mobile"
        label="手机号"
        rules={[{ pattern: /^1\d{10}$/, message: '请输入 11 位手机号' }]}
      />
      <ProFormText
        name="email"
        label="邮箱"
        fieldProps={{ maxLength: 100 }}
        rules={[{ type: 'email', message: '邮箱格式不正确' }]}
      />
      {!editing && (
        <Form.Item
          name="role_ids"
          label="角色"
          extra={
            !orgId
              ? '请先选择所属组织'
              : roles.isError
                ? '可分配角色加载失败，请重新选择组织重试'
                : undefined
          }
        >
          <Select
            mode="multiple"
            allowClear
            disabled={!orgId}
            loading={roles.isFetching}
            placeholder="可选，不选则创建后再分配"
            notFoundContent="没有可分配的角色"
            options={(roles.data ?? []).map((r) => ({ value: r.id, label: r.name }))}
          />
        </Form.Item>
      )}
      {!editing && (
        <>
          <ProFormSwitch name="auto_password" label="系统生成初始密码" />
          {!autoPassword && (
            <ProFormText.Password
              name="password"
              label="初始密码"
              extra="8~32 位，必须同时包含字母和数字；用户首次登录须修改"
              rules={[
                { required: true, message: '请输入初始密码' },
                {
                  pattern: /^(?=.*[A-Za-z])(?=.*\d).{8,32}$/,
                  message: '8~32 位，同时包含字母和数字',
                },
              ]}
            />
          )}
        </>
      )}
    </ModalForm>
  );
}
