import { CopyOutlined } from '@ant-design/icons';
import { Alert, App, Button, Checkbox, Modal, Typography } from 'antd';
import { useState } from 'react';
import { copyText } from '@/utils/clipboard';

interface Props {
  title: string;
  keyName: string;
  /** 明文只通过 props 传入，不写入任何缓存或存储；关闭后由父组件丢弃 */
  secret: string;
  onClose: () => void;
}

/** 一次性展示 API 密钥明文：必须勾选"我已妥善保存"才能关闭（AC-52） */
export default function ApiKeySecretModal({ title, keyName, secret, onClose }: Props) {
  const { message } = App.useApp();
  const [saved, setSaved] = useState(false);

  const copy = async () => {
    const ok = await copyText(secret);
    if (ok) void message.success('已复制到剪贴板');
    else void message.error('复制失败，请手动选中复制');
  };

  return (
    <Modal
      open
      title={title}
      width={560}
      maskClosable={false}
      closable={false}
      keyboard={false}
      footer={
        <Button type="primary" disabled={!saved} onClick={onClose}>
          关闭
        </Button>
      }
    >
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="关闭后将无法再次查看该密钥，请立即复制并妥善保存；遗失后只能重新生成（旧密钥随即失效）。"
      />
      <p>
        密钥名称：<strong>{keyName}</strong>
      </p>
      <div
        style={{
          display: 'flex',
          gap: 8,
          alignItems: 'center',
          marginBottom: 16,
        }}
      >
        <Typography.Text code data-testid="api-key-secret" style={{ wordBreak: 'break-all' }}>
          {secret}
        </Typography.Text>
        <Button icon={<CopyOutlined />} onClick={() => void copy()}>
          复制
        </Button>
      </div>
      <Checkbox checked={saved} onChange={(e) => setSaved(e.target.checked)}>
        我已妥善保存
      </Checkbox>
    </Modal>
  );
}
