import { useQuery, useQueryClient } from '@tanstack/react-query';
import { App, Button, Checkbox, Empty, Modal, Result, Skeleton, Space, Tag } from 'antd';
import { useState } from 'react';
import { roleApi, userApi } from '@/services/iam';
import type { UserItem } from '@/services/types/iam-contract';
import { useAuthStore } from '@/stores/auth';
import { submitWithLockoutConfirm } from '@/utils/lockout';
import { notifyError } from '@/utils/notify';

interface Props {
  user: UserItem;
  onClose: () => void;
  onDone: () => void;
}

export default function AssignRolesModal({ user, onClose, onDone }: Props) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['assignable-roles', user.id],
    queryFn: () => roleApi.assignable({ user_id: user.id }),
    gcTime: 0,
  });
  const [selected, setSelected] = useState<number[] | null>(null);
  const [saving, setSaving] = useState(false);
  const current = selected ?? (data ?? []).filter((r) => r.assigned).map((r) => r.id);

  const confirm = (content: string) =>
    new Promise<boolean>((resolve) => {
      modal.confirm({
        title: '保存后您将失去该页面权限',
        content,
        okText: '确认保存',
        okButtonProps: { danger: true },
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });

  const handleOk = async () => {
    setSaving(true);
    try {
      await submitWithLockoutConfirm(
        (confirmSelfLockout) =>
          userApi.assignRoles(user.id, {
            role_ids: current,
            confirm_self_lockout: confirmSelfLockout,
          }),
        confirm,
      );
      void message.success('角色已更新');
      if (user.id === useAuthStore.getState().user?.id) {
        await useAuthStore
          .getState()
          .loadMe()
          .catch(() => undefined);
      }
      void queryClient.invalidateQueries({ queryKey: ['assignable-roles'] });
      onDone();
    } catch (err) {
      notifyError(err);
    } finally {
      setSaving(false);
    }
  };

  let body;
  if (isLoading) body = <Skeleton active />;
  else if (isError)
    body = (
      <Result
        status="error"
        title="加载可分配角色失败"
        extra={<Button onClick={() => void refetch()}>重试</Button>}
      />
    );
  else if (!data || data.length === 0) body = <Empty description="没有可分配给该用户的角色" />;
  else
    body = (
      <Checkbox.Group
        value={current}
        onChange={(v) => setSelected(v as number[])}
        style={{ width: '100%' }}
      >
        <Space direction="vertical">
          {data.map((r) => (
            <Checkbox key={r.id} value={r.id}>
              {r.name} <Tag>{r.role_type === 'group' ? '集团级' : '公司级'}</Tag>
            </Checkbox>
          ))}
        </Space>
      </Checkbox.Group>
    );

  return (
    <Modal
      open
      title={`分配角色：${user.name}（${user.username}）`}
      onCancel={onClose}
      onOk={() => void handleOk()}
      okButtonProps={{ loading: saving, disabled: isLoading || isError }}
      maskClosable={false}
      destroyOnClose
    >
      {body}
    </Modal>
  );
}
