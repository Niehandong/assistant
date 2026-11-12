import { ModalForm } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { App, Checkbox, Form, Radio, TreeSelect } from 'antd';
import { assignmentApi } from '@/services/kb';
import type { AssignPermission, AssignTargetType } from '@/services/types/kb-contract';
import { notifyError } from '@/utils/notify';
import AssignableUserSelect from '../../../components/AssignableUserSelect';
import {
  PERMISSION_LEVEL_LABEL,
  TARGET_TYPE_LABEL,
  defaultIncludeChildren,
  includeChildrenLabel,
  toOrgTreeData,
} from '../logic';

interface Values {
  target_type: AssignTargetType;
  target_id?: number;
  include_children: boolean;
  permission: AssignPermission;
}

interface Props {
  datasetId: number;
  onClose: () => void;
  onSuccess: () => void;
}

export default function AddAssignmentModal({ datasetId, onClose, onSuccess }: Props) {
  const [form] = Form.useForm<Values>();
  const { message } = App.useApp();
  const type = Form.useWatch('target_type', form) ?? 'user';
  const { data: orgs, isLoading } = useQuery({
    queryKey: ['kb-assignable-orgs', datasetId],
    queryFn: () => assignmentApi.assignableOrgs(datasetId),
    enabled: type !== 'user',
  });

  return (
    <ModalForm<Values>
      open
      form={form}
      title="添加分配"
      width={520}
      layout="vertical"
      modalProps={{ destroyOnClose: true, maskClosable: false, onCancel: onClose }}
      initialValues={{ target_type: 'user', include_children: false, permission: 'read' }}
      onValuesChange={(changed: Partial<Values>) => {
        if (changed.target_type) {
          form.setFieldsValue({
            target_id: undefined,
            include_children: defaultIncludeChildren(changed.target_type),
          });
        }
      }}
      onFinish={async (v) => {
        try {
          await assignmentApi.create(datasetId, {
            target_type: v.target_type,
            target_id: v.target_id as number,
            include_children: v.target_type === 'user' ? undefined : v.include_children,
            permission: v.permission,
          });
        } catch (err) {
          notifyError(err);
          return false;
        }
        void message.success('已添加分配');
        onSuccess();
        return true;
      }}
    >
      <Form.Item name="target_type" label="分配对象类型">
        <Radio.Group
          options={(Object.keys(TARGET_TYPE_LABEL) as AssignTargetType[]).map((k) => ({
            value: k,
            label: TARGET_TYPE_LABEL[k],
          }))}
          optionType="button"
        />
      </Form.Item>
      <Form.Item
        name="target_id"
        label={TARGET_TYPE_LABEL[type]}
        rules={[{ required: true, message: `请选择${TARGET_TYPE_LABEL[type]}` }]}
        extra="仅可分配给您所属公司及其下属范围内的对象"
      >
        {type === 'user' ? (
          <AssignableUserSelect datasetId={datasetId} />
        ) : (
          <TreeSelect
            key={type}
            showSearch
            treeNodeFilterProp="title"
            treeDefaultExpandAll
            loading={isLoading}
            treeData={toOrgTreeData(orgs ?? [], type)}
            placeholder={type === 'dept' ? '请选择部门' : '请选择公司'}
            aria-label={TARGET_TYPE_LABEL[type]}
          />
        )}
      </Form.Item>
      {type !== 'user' && (
        <Form.Item name="include_children" valuePropName="checked">
          <Checkbox>{includeChildrenLabel(type)}</Checkbox>
        </Form.Item>
      )}
      <Form.Item name="permission" label="权限级别">
        <Radio.Group
          options={(Object.keys(PERMISSION_LEVEL_LABEL) as AssignPermission[]).map((k) => ({
            value: k,
            label: PERMISSION_LEVEL_LABEL[k],
          }))}
        />
      </Form.Item>
    </ModalForm>
  );
}
