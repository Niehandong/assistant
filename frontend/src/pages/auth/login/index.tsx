import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { LoginForm, ProFormText } from '@ant-design/pro-components';
import { useQueryClient } from '@tanstack/react-query';
import { Alert } from 'antd';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { tokenStore } from '@/api/tokenStore';
import { authApi } from '@/services/iam';
import type { LoginRequest } from '@/services/types/iam-contract';
import { useAuthStore } from '@/stores/auth';
import { safeRedirect } from '@/utils/redirect';
import { getLoginErrorMessage } from './messages';

export default function LoginPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const queryClient = useQueryClient();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // onFinish 返回 Promise 期间表单提交按钮自动 loading，防止重复提交
  const handleFinish = async (values: LoginRequest): Promise<void> => {
    setErrorMsg(null);
    try {
      // 清理上一个账号遗留的状态与缓存
      useAuthStore.getState().reset();
      queryClient.clear();
      const token = await authApi.login({
        username: values.username.trim(),
        password: values.password,
      });
      tokenStore.set(token.access_token, token.refresh_token);
      await useAuthStore.getState().loadMe();
      if (token.must_change_password) {
        navigate('/change-password', { replace: true });
      } else {
        navigate(safeRedirect(params.get('redirect')), { replace: true });
      }
    } catch (err) {
      tokenStore.clear();
      setErrorMsg(getLoginErrorMessage(err));
    }
  };

  return (
    <div
      style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', background: '#f5f7fa' }}
    >
      <LoginForm<LoginRequest>
        title="知识库平台"
        subTitle="使用账号密码登录"
        onFinish={handleFinish}
        submitter={{ searchConfig: { submitText: '登录' } }}
      >
        {errorMsg && (
          <Alert type="error" showIcon message={errorMsg} style={{ marginBottom: 16 }} />
        )}
        <ProFormText
          name="username"
          fieldProps={{
            size: 'large',
            prefix: <UserOutlined />,
            maxLength: 64,
            autoComplete: 'username',
          }}
          placeholder="账号"
          rules={[{ required: true, whitespace: true, message: '请输入账号' }]}
        />
        <ProFormText.Password
          name="password"
          fieldProps={{
            size: 'large',
            prefix: <LockOutlined />,
            maxLength: 64,
            autoComplete: 'current-password',
          }}
          placeholder="密码"
          rules={[{ required: true, message: '请输入密码' }]}
        />
      </LoginForm>
    </div>
  );
}
