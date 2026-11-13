import { ProForm, ProFormText } from '@ant-design/pro-components';
import { App, Button, Card, Form } from 'antd';
import { useNavigate } from 'react-router-dom';
import { authApi } from '@/services/iam';
import { useAuthStore } from '@/stores/auth';
import { ApiError, getErrorMessage, getFieldErrors } from '@/utils/error';
import AuthShell from '../AuthShell';
import { validateNewPassword } from './rules';

interface FormValues {
  old_password: string;
  new_password: string;
  confirm_password: string;
}

export default function ChangePasswordPage() {
  const [form] = Form.useForm<FormValues>();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const user = useAuthStore((s) => s.user);
  const forced = user?.must_change_password ?? false;

  const handleFinish = async (values: FormValues): Promise<void> => {
    try {
      await authApi.changePassword({
        old_password: values.old_password,
        new_password: values.new_password,
      });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === 400101) {
          form.setFields([{ name: 'old_password', errors: [err.message] }]);
          return;
        }
        if (err.code === 400102 || err.code === 400103) {
          const detail = getFieldErrors(err)[0]?.message;
          form.setFields([{ name: 'new_password', errors: [detail ?? err.message] }]);
          return;
        }
      }
      void message.error(getErrorMessage(err));
      return;
    }
    void message.success('密码修改成功');
    try {
      await useAuthStore.getState().loadMe();
      navigate('/', { replace: true });
    } catch {
      navigate('/login', { replace: true });
    }
  };

  const handleLogout = async () => {
    const done = useAuthStore.getState().logout();
    navigate('/login', { replace: true });
    await done;
  };

  return (
    <AuthShell>
      <Card
        title={forced ? '首次登录，请先修改密码' : '修改密码'}
        extra={
          <Button type="link" onClick={handleLogout}>
            退出登录
          </Button>
        }
      >
        <ProForm<FormValues>
          form={form}
          layout="vertical"
          onFinish={handleFinish}
          submitter={{
            searchConfig: { submitText: '确认修改' },
            resetButtonProps: { style: { display: 'none' } },
            render: (_, dom) => dom[1],
          }}
        >
          <ProFormText.Password
            name="old_password"
            label="当前密码"
            fieldProps={{ maxLength: 64, autoComplete: 'current-password' }}
            rules={[{ required: true, message: '请输入当前密码' }]}
          />
          <ProFormText.Password
            name="new_password"
            label="新密码"
            extra="8~32 位，必须同时包含字母和数字，且不能与当前密码相同"
            fieldProps={{ maxLength: 32, autoComplete: 'new-password' }}
            dependencies={['old_password']}
            rules={[
              { required: true, message: '请输入新密码' },
              ({ getFieldValue }) => ({
                validator: (_, value: string | undefined) => {
                  if (!value) return Promise.resolve();
                  const msg = validateNewPassword(value, getFieldValue('old_password'));
                  return msg ? Promise.reject(new Error(msg)) : Promise.resolve();
                },
              }),
            ]}
          />
          <ProFormText.Password
            name="confirm_password"
            label="确认新密码"
            fieldProps={{ maxLength: 32, autoComplete: 'new-password' }}
            dependencies={['new_password']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator: (_, value: string | undefined) =>
                  !value || value === getFieldValue('new_password')
                    ? Promise.resolve()
                    : Promise.reject(new Error('两次输入的密码不一致')),
              }),
            ]}
          />
        </ProForm>
      </Card>
    </AuthShell>
  );
}
