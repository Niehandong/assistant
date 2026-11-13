import { ModalForm } from '@ant-design/pro-components';
import { Alert, App, Form } from 'antd';
import { useState } from 'react';
import { adminDatasetApi } from '@/services/kb';
import type { AdminDatasetItem } from '@/services/types/kb-contract';
import { buildTransferBody, parseTransferError } from '../logic';
import AdminReceiverSelect from './AdminReceiverSelect';

interface Props {
  dataset: Pick<AdminDatasetItem, 'id' | 'name' | 'owner' | 'version'>;
  onClose: () => void;
  onTransferred: () => void;
}

/** 单个知识库转移所有权（管理员） */
export default function AdminTransferModal({ dataset, onClose, onTransferred }: Props) {
  const [form] = Form.useForm<{ receiver_user_id: number }>();
  const { message } = App.useApp();
  const [error, setError] = useState<string | null>(null);

  return (
    <ModalForm<{ receiver_user_id: number }>
      open
      form={form}
      title={`转移知识库「${dataset.name}」的所有权`}
      width={480}
      layout="vertical"
      modalProps={{ destroyOnClose: true, maskClosable: false, onCancel: onClose }}
      submitter={{ searchConfig: { submitText: '确认转移' }, submitButtonProps: { danger: true } }}
      onFinish={async (v) => {
        setError(null);
        try {
          await adminDatasetApi.transfer(
            dataset.id,
            buildTransferBody(dataset, v.receiver_user_id),
          );
        } catch (err) {
          setError(parseTransferError(err).message);
          return false;
        }
        void message.success('所有权已转移');
        onTransferred();
        return true;
      }}
    >
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message={`当前所有者：${dataset.owner.name}。转移后其将失去访问权限，已有分配保持不变，所属公司/部门改为接收人所在组织。`}
      />
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
      <Form.Item
        name="receiver_user_id"
        label="接收人"
        rules={[{ required: true, message: '请选择接收人' }]}
        extra="仅可转移给您数据范围内的启用用户；接收人名下不能有同名知识库"
      >
        <AdminReceiverSelect />
      </Form.Item>
    </ModalForm>
  );
}
