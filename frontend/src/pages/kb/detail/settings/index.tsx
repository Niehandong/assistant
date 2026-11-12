import { Alert, App, Button, Card, Result, Space, Typography } from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { datasetApi } from '@/services/kb';
import { notifyError } from '@/utils/notify';
import { usePermission } from '@/access/usePermission';
import DeleteDatasetModal from '../../components/DeleteDatasetModal';
import { datasetDetailKey, useDataset } from '../useDataset';
import BasicInfoForm from './components/BasicInfoForm';
import RetrievalSection from './components/RetrievalSection';
import TransferModal from './components/TransferModal';
import { dangerZoneAccess, type VersionGuard } from './logic';

type Dialog = 'transfer' | 'delete' | null;

export default function SettingsPage() {
  const dataset = useDataset();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const can = usePermission();
  const { message, modal } = App.useApp();
  const [dialog, setDialog] = useState<Dialog>(null);
  // 保存使用的 version：只有本页保存成功或用户确认刷新才会推进，冲突后继续用旧值（继续得到 409001）
  const [baseVersion, setBaseVersion] = useState(dataset.version);
  const [conflict, setConflict] = useState(false);
  const [resetKey, setResetKey] = useState(0);

  if (dataset.my_permission === 'read' || !can('kb:dataset:update')) {
    return <Result status="403" title="您没有修改该知识库设置的权限" />;
  }
  const guard: VersionGuard = {
    version: baseVersion,
    onSaved: setBaseVersion,
    onConflict: () => {
      setConflict(true);
      void message.error('该知识库已被他人修改');
    },
  };
  const refresh = () =>
    modal.confirm({
      title: '刷新并放弃本地修改？',
      content: '将重新加载最新数据到表单，您尚未保存的修改会丢失。',
      okText: '刷新',
      onOk: async () => {
        try {
          const fresh = await datasetApi.detail(dataset.id);
          qc.setQueryData(datasetDetailKey(dataset.id), fresh);
          setBaseVersion(fresh.version);
          setConflict(false);
          setResetKey((k) => k + 1);
        } catch (err) {
          notifyError(err);
          throw err; // 保持弹窗，允许重试
        }
      },
    });
  const danger = dangerZoneAccess(dataset.my_permission, can);
  const leave = () => {
    void qc.invalidateQueries({ queryKey: ['kb-datasets'] });
    navigate('/kb/datasets', { replace: true });
  };

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {/* 两个表单各自保存；仅用户确认刷新时（resetKey）才重置表单 */}
      {conflict && (
        <Alert
          type="warning"
          showIcon
          message="该知识库已被他人修改"
          description="在刷新之前，保存仍会被拒绝，以免覆盖他人的修改。刷新会放弃您本地尚未保存的修改。"
          action={
            <Button size="small" type="primary" onClick={refresh}>
              刷新
            </Button>
          }
        />
      )}
      <BasicInfoForm key={`basic-${resetKey}`} dataset={dataset} guard={guard} />
      <RetrievalSection key={`retrieval-${resetKey}`} dataset={dataset} guard={guard} />
      {(danger.canTransfer || danger.canDelete) && (
        <Card title={<Typography.Text type="danger">危险操作</Typography.Text>} size="small">
          <Space direction="vertical" size={12}>
            {danger.canTransfer && (
              <Space>
                <Button onClick={() => setDialog('transfer')}>转移所有权</Button>
                <Typography.Text type="secondary">转移后您将失去所有者身份</Typography.Text>
              </Space>
            )}
            {danger.canDelete && (
              <Space>
                <Button danger onClick={() => setDialog('delete')}>
                  删除知识库
                </Button>
                <Typography.Text type="secondary">
                  删除后文档与分段一并删除，不可恢复
                </Typography.Text>
              </Space>
            )}
          </Space>
        </Card>
      )}
      {dialog === 'transfer' && (
        <TransferModal dataset={dataset} onClose={() => setDialog(null)} onTransferred={leave} />
      )}
      {dialog === 'delete' && (
        <DeleteDatasetModal dataset={dataset} onClose={() => setDialog(null)} onDeleted={leave} />
      )}
    </Space>
  );
}
