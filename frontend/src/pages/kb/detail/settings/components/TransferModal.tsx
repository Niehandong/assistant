import { ModalForm } from '@ant-design/pro-components';
import { Alert, App, Form } from 'antd';
import { datasetApi } from '@/services/kb';
import type { DatasetDetail } from '@/services/types/kb-contract';
import { notifyError } from '@/utils/notify';
import AssignableUserSelect from '../../../components/AssignableUserSelect';

interface Props {
  dataset: DatasetDetail;
  onClose: () => void;
  /** 转移成功：调用者此后通常已无访问权，由页面跳回列表 */
  onTransferred: () => void;
}

export default function TransferModal({ dataset, onClose, onTransferred }: Props) {
  const [form] = Form.useForm<{ receiver_user_id: number }>();
  const { message } = App.useApp();
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
        try {
          await datasetApi.transfer(dataset.id, {
            receiver_user_id: v.receiver_user_id,
            version: dataset.version,
          });
        } catch (err) {
          notifyError(err);
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
        message="转移后您将失去该知识库的所有者身份，原所有者将失去访问权限（除非另有分配途径）。"
      />
      <Form.Item
        name="receiver_user_id"
        label="接收人"
        rules={[{ required: true, message: '请选择接收人' }]}
        extra="仅可转移给本公司及下属公司内的启用用户；接收人名下不能有同名知识库"
      >
        <AssignableUserSelect datasetId={dataset.id} />
      </Form.Item>
    </ModalForm>
  );
}
