import { ModalForm, ProFormSwitch, ProFormText } from '@ant-design/pro-components';
import { Form } from 'antd';
import { userApi } from '@/services/iam';
import type { UserItem } from '@/services/types/iam-contract';
import { notifyError } from '@/utils/notify';

interface Props {
  user: UserItem;
  onClose: () => void;
  /** password 为系统生成的明文（手动指定时为 null） */
  onDone: (password: string | null) => void;
}

export default function ResetPasswordModal({ user, onClose, onDone }: Props) {
  const [form] = Form.useForm<{ auto_password: boolean; password?: string }>();
  const auto = Form.useWatch('auto_password', form);
  return (
    <ModalForm<{ auto_password: boolean; password?: string }>
      title={`重置密码：${user.name}（${user.username}）`}
      open
      form={form}
      width={480}
      layout="vertical"
      modalProps={{ destroyOnClose: true, maskClosable: false, onCancel: onClose }}
      initialValues={{ auto_password: true }}
      onFinish={async (v) => {
        try {
          const res = await userApi.resetPassword(user.id, {
            password: v.auto_password ? undefined : v.password,
          });
          onDone(res.password);
          return true;
        } catch (err) {
          notifyError(err);
          return false;
        }
      }}
    >
      <p>重置后，该用户的所有会话将立即失效，首次登录须修改密码。</p>
      <ProFormSwitch name="auto_password" label="系统生成随机密码" />
      {!auto && (
        <ProFormText.Password
          name="password"
          label="新密码"
          extra="8~32 位，必须同时包含字母和数字"
          rules={[
            { required: true, message: '请输入新密码' },
            { pattern: /^(?=.*[A-Za-z])(?=.*\d).{8,32}$/, message: '8~32 位，同时包含字母和数字' },
          ]}
        />
      )}
    </ModalForm>
  );
}
