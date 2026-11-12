import { PlusOutlined } from '@ant-design/icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { App, Button, Card, Descriptions, Result, Space, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useState } from 'react';
import { usePermission } from '@/access/usePermission';
import { assignmentApi } from '@/services/kb';
import type { AssignmentItem } from '@/services/types/kb-contract';
import { getErrorMessage } from '@/utils/error';
import { formatDateTime } from '@/utils/format';
import { notifyError } from '@/utils/notify';
import { ownerText } from '../../list/logic';
import { useDataset, useRefreshDataset } from '../useDataset';
import AddAssignmentModal from './components/AddAssignmentModal';
import EditAssignmentModal from './components/EditAssignmentModal';
import {
  PERMISSION_LEVEL_LABEL,
  TARGET_TYPE_LABEL,
  canManageAssignments,
  targetDescription,
} from './logic';

type Dialog = { type: 'add' } | { type: 'edit'; item: AssignmentItem } | null;

export default function AssignmentsPage() {
  const dataset = useDataset();
  const can = usePermission();
  const qc = useQueryClient();
  const { modal, message } = App.useApp();
  const refreshDataset = useRefreshDataset(dataset.id);
  const [dialog, setDialog] = useState<Dialog>(null);
  const manage = canManageAssignments(dataset.my_permission, can);
  const key = ['kb-assignments', dataset.id];
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: key,
    queryFn: () => assignmentApi.list(dataset.id),
    enabled: dataset.my_permission !== 'read',
  });

  if (dataset.my_permission === 'read') {
    return <Result status="403" title="您没有查看分配名单的权限" />;
  }

  const reload = () => {
    void qc.invalidateQueries({ queryKey: key });
    void refreshDataset();
  };

  const remove = (a: AssignmentItem) =>
    modal.confirm({
      title: `确认移除对「${a.target_name}」的分配？`,
      content: '移除后立即生效，该对象将失去对此知识库的访问权限。',
      okText: '移除',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await assignmentApi.remove(dataset.id, a.id);
          void message.success('已移除');
          reload();
        } catch (err) {
          notifyError(err);
        }
      },
    });

  const columns: ColumnsType<AssignmentItem> = [
    {
      title: '分配对象',
      dataIndex: 'target_name',
      render: (_, a) => (
        <Space direction="vertical" size={0}>
          <span>{targetDescription(a)}</span>
          {a.target_path && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {a.target_path}
            </Typography.Text>
          )}
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'target_type',
      width: 80,
      render: (v) => TARGET_TYPE_LABEL[v as AssignmentItem['target_type']],
    },
    {
      title: '含下级',
      dataIndex: 'include_children',
      width: 80,
      render: (v, a) => (a.target_type === 'user' ? '-' : v ? '是' : '否'),
    },
    {
      title: '权限',
      dataIndex: 'permission',
      width: 90,
      render: (v: AssignmentItem['permission']) => (
        <Tag color={v === 'edit' ? 'cyan' : 'default'}>{PERMISSION_LEVEL_LABEL[v]}</Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'target_valid',
      width: 90,
      render: (v: boolean) =>
        v ? <Tag color="success">有效</Tag> : <Tag color="error">已失效</Tag>,
    },
    { title: '添加人', dataIndex: 'created_by', width: 100, render: (_, a) => a.created_by.name },
    {
      title: '添加时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => formatDateTime(v),
    },
  ];
  if (manage) {
    columns.push({
      title: '操作',
      key: 'action',
      width: 130,
      fixed: 'right',
      render: (_, a) => (
        <Space size={0}>
          {a.target_valid && (
            <Button type="link" size="small" onClick={() => setDialog({ type: 'edit', item: a })}>
              修改
            </Button>
          )}
          <Button type="link" size="small" danger onClick={() => remove(a)}>
            移除
          </Button>
        </Space>
      ),
    });
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card size="small" title="所有者">
        <Descriptions column={3} size="small">
          <Descriptions.Item label="姓名">{ownerText(dataset)}</Descriptions.Item>
          <Descriptions.Item label="所属公司">{dataset.owner_org.company_name}</Descriptions.Item>
          <Descriptions.Item label="所属部门">{dataset.owner_org.dept_name}</Descriptions.Item>
        </Descriptions>
      </Card>
      <Card
        size="small"
        title="分配名单"
        extra={
          manage && (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setDialog({ type: 'add' })}
            >
              添加分配
            </Button>
          )
        }
      >
        {!manage && (
          <Typography.Paragraph type="secondary">
            只有所有者可以添加、修改和移除分配，您可以查看名单。
          </Typography.Paragraph>
        )}
        {error ? (
          <Result
            status="error"
            title="加载失败"
            subTitle={getErrorMessage(error)}
            extra={
              <Button type="primary" onClick={() => void refetch()}>
                重试
              </Button>
            }
          />
        ) : (
          <Table<AssignmentItem>
            rowKey="id"
            size="middle"
            loading={isLoading}
            columns={columns}
            dataSource={data ?? []}
            pagination={false}
            scroll={{ x: 900 }}
            locale={{ emptyText: '尚未分配给任何对象' }}
            rowClassName={(a) => (a.target_valid ? '' : 'ant-table-row-disabled')}
          />
        )}
      </Card>
      {dialog?.type === 'add' && (
        <AddAssignmentModal
          datasetId={dataset.id}
          onClose={() => setDialog(null)}
          onSuccess={() => {
            setDialog(null);
            reload();
          }}
        />
      )}
      {dialog?.type === 'edit' && (
        <EditAssignmentModal
          datasetId={dataset.id}
          assignment={dialog.item}
          onClose={() => setDialog(null)}
          onSuccess={() => {
            setDialog(null);
            reload();
          }}
        />
      )}
    </Space>
  );
}
