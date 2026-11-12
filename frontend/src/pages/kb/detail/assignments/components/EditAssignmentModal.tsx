import { ModalForm } from '@ant-design/pro-components';
import { App, Checkbox, Form, Radio } from 'antd';
import { assignmentApi } from '@/services/kb';
import type { AssignmentItem, AssignPermission } from '@/services/types/kb-contract';
import { notifyError } from '@/utils/notify';
import { PERMISSION_LEVEL_LABEL, includeChildrenLabel } from '../logic';

interface Values {
  permission: AssignPermission;
  include_children: boolean;
}

interface Props {
  datasetId: number;
  assignment: AssignmentItem;
  onClose: () => void;
  onSuccess: () => void;
}

export default function EditAssignmentModal({ datasetId, assignment, onClose, onSuccess }: Props) {
  const { message } = App.useApp();
  return (
    <ModalForm<Values>
      open
      title={`修改分配：${assignment.target_name}`}
      width={440}
      layout="vertical"
      modalProps={{ destroyOnClose: true, maskClosable: false, onCancel: onClose }}
      initialValues={{
        permission: assignment.permission,
        include_children: assignment.include_children,
      }}
      onFinish={async (v) => {
        try {
          await assignmentApi.update(datasetId, assignment.id, {
            permission: v.permission,
            include_children: assignment.target_type === 'user' ? false : v.include_children,
          });
        } catch (err) {
          notifyError(err);
          return false;
        }
        void message.success('已保存');
        onSuccess();
        return true;
      }}
    >
      <Form.Item name="permission" label="权限级别">
        <Radio.Group
          options={(Object.keys(PERMISSION_LEVEL_LABEL) as AssignPermission[]).map((k) => ({
            value: k,
            label: PERMISSION_LEVEL_LABEL[k],
          }))}
        />
      </Form.Item>
      {assignment.target_type !== 'user' && (
        <Form.Item name="include_children" valuePropName="checked">
          <Checkbox>{includeChildrenLabel(assignment.target_type)}</Checkbox>
        </Form.Item>
      )}
    </ModalForm>
  );
}
