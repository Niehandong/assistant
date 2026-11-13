import { useQuery } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Checkbox,
  Drawer,
  Empty,
  Radio,
  Result,
  Skeleton,
  Space,
  Tree,
} from 'antd';
import { useMemo, useState } from 'react';
import OrgTreeSelect from '@/components/OrgTreeSelect';
import { useOrgOptions } from '@/hooks/useOrgOptions';
import { roleApi } from '@/services/iam';
import type {
  DataScope,
  PermissionTreeResult,
  RoleDetail,
  RoleItem,
} from '@/services/types/iam-contract';
import { submitWithLockoutConfirm } from '@/utils/lockout';
import { notifyError } from '@/utils/notify';
import {
  DATA_SCOPE_LABEL,
  DATA_SCOPE_ORDER,
  buildGrantBody,
  flattenPermissions,
  grantErrorMessage,
  isScopeDisabled,
  toPermTreeData,
} from '../grantLogic';

interface EditorProps {
  role: RoleDetail;
  perm: PermissionTreeResult;
  onClose: () => void;
  onSuccess: () => void;
}

function GrantEditor({ role, perm, onClose, onSuccess }: EditorProps) {
  const { message, modal } = App.useApp();
  const orgs = useOrgOptions();
  const [checked, setChecked] = useState<number[]>(role.permission_ids);
  const [dataScope, setDataScope] = useState<DataScope>(role.data_scope);
  const [customOrgIds, setCustomOrgIds] = useState<number[]>(role.custom_org_ids);
  const [includeChildren, setIncludeChildren] = useState(false);
  const [saving, setSaving] = useState(false);
  const treeData = useMemo(() => toPermTreeData(perm.tree), [perm.tree]);
  const lockedCount = useMemo(() => {
    const locked = new Set(
      flattenPermissions(perm.tree)
        .filter((n) => !n.grantable)
        .map((n) => n.id),
    );
    return role.permission_ids.filter((id) => locked.has(id)).length;
  }, [perm.tree, role.permission_ids]);

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

  const handleSave = async () => {
    if (dataScope === 'CUSTOM' && customOrgIds.length === 0) {
      void message.warning('自定义数据范围必须至少选择一个组织');
      return;
    }
    const body = buildGrantBody(
      { checked, dataScope, customOrgIds, includeChildren },
      perm.tree,
      orgs.data ?? [],
      role.version,
    );
    setSaving(true);
    try {
      await submitWithLockoutConfirm(
        (confirmSelfLockout) =>
          roleApi.grant(role.id, { ...body, confirm_self_lockout: confirmSelfLockout }),
        confirm,
      );
      void message.success('授权已保存，用户刷新页面后生效');
      onSuccess();
    } catch (err) {
      const friendly = grantErrorMessage(err, perm.tree);
      if (friendly) void message.error(friendly);
      else notifyError(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div style={{ display: 'flex', gap: 24 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h4>功能权限</h4>
          {lockedCount > 0 && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 8 }}
              message={`有 ${lockedCount} 项权限超出您的授权范围，已置灰保留，无法修改`}
            />
          )}
          {treeData.length === 0 ? (
            <Empty description="暂无权限点" />
          ) : (
            <Tree
              checkable
              checkStrictly
              defaultExpandAll
              treeData={treeData}
              checkedKeys={checked}
              onCheck={(keys) =>
                setChecked((Array.isArray(keys) ? keys : keys.checked) as number[])
              }
            />
          )}
        </div>
        <div style={{ width: 280, flexShrink: 0 }}>
          <h4>数据范围</h4>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 8 }}
            message="用户拥有多个角色时，数据范围取所有启用角色的并集，并对该用户拥有的所有功能生效。"
          />
          <Radio.Group
            value={dataScope}
            onChange={(e) => setDataScope(e.target.value as DataScope)}
          >
            <Space direction="vertical">
              {DATA_SCOPE_ORDER.map((s) => (
                <Radio key={s} value={s} disabled={isScopeDisabled(s, perm)}>
                  {DATA_SCOPE_LABEL[s]}
                </Radio>
              ))}
            </Space>
          </Radio.Group>
          {dataScope === 'CUSTOM' && (
            <div style={{ marginTop: 12 }}>
              <OrgTreeSelect
                multiple
                disableUnmanageable
                value={customOrgIds}
                onChange={(v) => setCustomOrgIds(Array.isArray(v) ? v : v ? [v] : [])}
                placeholder="选择可见组织"
              />
              <Checkbox
                style={{ marginTop: 8 }}
                checked={includeChildren}
                onChange={(e) => setIncludeChildren(e.target.checked)}
              >
                包含下级组织（提交时展开为具体组织）
              </Checkbox>
            </div>
          )}
        </div>
      </div>
      <div style={{ marginTop: 24, textAlign: 'right' }}>
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={saving} onClick={() => void handleSave()}>
            保存
          </Button>
        </Space>
      </div>
    </>
  );
}

export default function GrantDrawer({
  role,
  onClose,
  onSuccess,
}: {
  role: RoleItem;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const detail = useQuery({
    queryKey: ['role-detail', role.id],
    queryFn: () => roleApi.detail(role.id),
    gcTime: 0,
  });
  const perm = useQuery({
    queryKey: ['permission-tree'],
    queryFn: () => roleApi.permissionTree(),
    gcTime: 0,
  });
  let body;
  if (detail.isLoading || perm.isLoading) body = <Skeleton active paragraph={{ rows: 10 }} />;
  else if (detail.isError || perm.isError || !detail.data || !perm.data)
    body = (
      <Result
        status="error"
        title="加载失败"
        extra={
          <Button
            onClick={() => {
              void detail.refetch();
              void perm.refetch();
            }}
          >
            重试
          </Button>
        }
      />
    );
  else
    body = (
      <GrantEditor role={detail.data} perm={perm.data} onClose={onClose} onSuccess={onSuccess} />
    );

  return (
    <Drawer
      open
      width={860}
      title={`分配权限：${role.name}`}
      onClose={onClose}
      destroyOnClose
      maskClosable={false}
    >
      {body}
    </Drawer>
  );
}
