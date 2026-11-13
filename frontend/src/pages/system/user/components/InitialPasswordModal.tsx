import { Alert, Button, Modal, Typography } from 'antd';

interface Props {
  title: string;
  username: string;
  password: string;
  onClose: () => void;
}

/** 展示系统生成的初始密码，关闭后不可再看 */
export default function InitialPasswordModal({ title, username, password, onClose }: Props) {
  return (
    <Modal
      open
      title={title}
      maskClosable={false}
      closable={false}
      footer={
        <Button type="primary" onClick={onClose}>
          我已保存，关闭
        </Button>
      }
    >
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="该密码只显示一次，关闭后无法再次查看，请立即复制并告知用户。用户首次登录须修改密码。"
      />
      <p>账号：{username}</p>
      <p>
        密码：
        <Typography.Text code copyable={{ text: password }}>
          {password}
        </Typography.Text>
      </p>
    </Modal>
  );
}
