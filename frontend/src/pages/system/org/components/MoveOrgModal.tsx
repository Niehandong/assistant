import { ModalForm } from '@ant-design/pro-components';
import { App, Form } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import OrgTreeSelect from '@/components/OrgTreeSelect';
import { ORG_OPTIONS_KEY, useOrgOptions } from '@/hooks/useOrgOptions';
import { orgApi } from '@/services/iam';
import type { OrgNode, OrgOption } from '@/services/types/iam-contract';
import { notifyError } from '@/utils/notify';
import { canBeChildOf, collectSubtreeIds, findNode } from '@/utils/orgTree';

interface Props {
  node: OrgNode;
  onClose: () => void;
  onSuccess: () => void;
}

export default function MoveOrgModal({ node, onClose, onSuccess }: Props) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { data: options } = useOrgOptions();
  const me = findNode(options ?? [], node.id);
  const blocked = new Set(me ? collectSubtreeIds(me) : [node.id]);
  // 自身、后代、以及类型不允许承载该节点的组织置灰
  const isDisabled = (n: OrgOption) =>
    blocked.has(n.id) || !canBeChildOf(node.org_type, n.org_type);

  return (
    <ModalForm<{ parent_id: number }>
      title={`移动组织：${node.name}`}
      open
      width={480}
      layout="vertical"
      modalProps={{ destroyOnClose: true, maskClosable: false, onCancel: onClose }}
      initialValues={{ parent_id: node.parent_id }}
      onFinish={async ({ parent_id }) => {
        if (parent_id === node.parent_id) {
          void message.info('新上级与当前上级相同');
          return false;
        }
        try {
          await orgApi.move(node.id, { parent_id, version: node.version });
        } catch (err) {
          notifyError(err);
          return false;
        }
        void message.success('移动成功');
        void queryClient.invalidateQueries({ queryKey: [ORG_OPTIONS_KEY] });
        onSuccess();
        return true;
      }}
    >
      <Form.Item
        name="parent_id"
        label="新的上级组织"
        extra="移动后，其下用户的所属公司将重新计算；不能移动到自身或下级之下"
        rules={[{ required: true, message: '请选择新的上级组织' }]}
      >
        <OrgTreeSelect allowClear={false} isDisabled={isDisabled} disableUnmanageable />
      </Form.Item>
    </ModalForm>
  );
}
