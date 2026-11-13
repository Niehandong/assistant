import { PlusOutlined } from '@ant-design/icons';
import { ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components';
import { App, Button, Space, Tag, Tooltip, Typography } from 'antd';
import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Access } from '@/access/Access';
import { useTableError } from '@/hooks/useTableError';
import { apiKeyApi } from '@/services/open';
import type { ApiKeyItem, ApiKeySecretResult, KeyStatus } from '@/services/types/open-contract';
import { formatDateTime } from '@/utils/format';
import AccessibleDatasetsModal from './components/AccessibleDatasetsModal';
import ApiKeyFormModal from './components/ApiKeyFormModal';
import ApiKeySecretModal from './components/ApiKeySecretModal';
import {
  STATUS_COLOR,
  STATUS_OPTIONS,
  ADMIN_DISABLED_HINT,
  expiresText,
  isAdminDisabledError,
  rowActions,
  scopeText,
  statusLabel,
} from './logic';

type Dialog = { type: 'form'; item?: ApiKeyItem } | { type: 'accessible'; item: ApiKeyItem } | null;

interface SecretState {
  title: string;
  name: string;
  secret: string;
}

interface Filters {
  name?: string;
  status?: KeyStatus;
}

/** 我的 API 密钥（F-17） */
export default function ApiKeysPage() {
  const actionRef = useRef<ActionType>();
  const { wrap, locale } = useTableError(actionRef);
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const [dialog, setDialog] = useState<Dialog>(null);
  // 明文只放在组件状态里，关闭即丢弃，不进入查询缓存
  const [secret, setSecret] = useState<SecretState | null>(null);
  const reload = () => actionRef.current?.reload();

  const showSecret = (title: string, res: ApiKeySecretResult) =>
    setSecret({ title, name: res.item.name, secret: res.api_key });

  // 403604/403605（已被管理员停用）：拦截器已提示后端 message，这里刷新列表使状态与按钮同步
  const onWriteError = (err: unknown) => {
    if (isAdminDisabledError(err)) reload();
  };

  const toggle = (r: ApiKeyItem, to: 'enabled' | 'disabled') => {
    const run = async () => {
      await apiKeyApi.updateStatus(r.id, { status: to, version: r.version });
      void message.success(to === 'enabled' ? '已启用' : '已停用');
      reload();
    };
    if (to === 'enabled') return void run().catch(onWriteError);
    modal.confirm({
      title: `停用密钥「${r.name}」？`,
      content: '停用后使用该密钥的调用会立即被拒绝，可随时重新启用。',
      okText: '停用',
      onOk: () => run().catch(onWriteError),
    });
  };

  const regenerate = (r: ApiKeyItem) =>
    modal.confirm({
      title: `重新生成密钥「${r.name}」？`,
      content: '旧密钥将立即失效，使用旧密钥的系统需要更换为新密钥。新密钥只显示一次。',
      okText: '重新生成',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const res = await apiKeyApi.regenerate(r.id, { version: r.version });
          showSecret('密钥已重新生成', res);
          reload();
        } catch (err) {
          onWriteError(err);
          // 错误提示由请求拦截器统一处理
        }
      },
    });

  const remove = (r: ApiKeyItem) =>
    modal.confirm({
      title: `删除密钥「${r.name}」？`,
      content: '删除后该密钥立即失效且不可恢复，其历史调用日志仍可查看。',
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await apiKeyApi.remove(r.id);
          void message.success('已删除');
          reload();
        } catch {
          // 错误提示由请求拦截器统一处理
        }
      },
    });

  const columns: ProColumns<ApiKeyItem>[] = [
    {
      title: '名称',
      dataIndex: 'name',
      width: 180,
      ellipsis: true,
      fieldProps: { placeholder: '按名称搜索' },
      render: (_, r) =>
        r.description ? <Tooltip title={r.description}>{r.name}</Tooltip> : r.name,
    },
    {
      title: '状态',
      dataIndex: 'status',
      valueType: 'select',
      fieldProps: { options: STATUS_OPTIONS, allowClear: true },
      width: 140,
      render: (_, r) => <Tag color={STATUS_COLOR[r.status]}>{statusLabel(r.status)}</Tag>,
    },
    { title: '密钥', dataIndex: 'key_masked', search: false, width: 130 },
    {
      title: '检索范围',
      search: false,
      width: 110,
      render: (_, r) => scopeText(r),
    },
    {
      title: '当前可检索',
      search: false,
      width: 100,
      render: (_, r) => (
        <Button type="link" size="small" onClick={() => setDialog({ type: 'accessible', item: r })}>
          {r.accessible_dataset_count} 个
        </Button>
      ),
    },
    {
      title: '过期时间',
      search: false,
      width: 170,
      render: (_, r) => expiresText(r.expires_at),
    },
    {
      title: '限流',
      search: false,
      width: 100,
      render: (_, r) => `${r.rate_limit_per_min} 次/分`,
    },
    {
      title: '近 7 天',
      search: false,
      width: 130,
      render: (_, r) => `调用 ${r.calls_7d} / 失败 ${r.failures_7d}`,
    },
    {
      title: '最近调用',
      search: false,
      width: 170,
      renderText: (_, r) => formatDateTime(r.last_used_at),
    },
    {
      title: '创建时间',
      search: false,
      width: 170,
      renderText: (_, r) => formatDateTime(r.created_at),
    },
    {
      title: '操作',
      valueType: 'option',
      fixed: 'right',
      width: 270,
      render: (_, r) => {
        const a = rowActions(r);
        return (
          <Space size={0} wrap>
            <Access code="openapi:apikey:manage">
              {r.stored_status === 'admin_disabled' && (
                <Tooltip title={ADMIN_DISABLED_HINT}>
                  <Typography.Text type="secondary" style={{ marginRight: 8, cursor: 'help' }}>
                    不可修改
                  </Typography.Text>
                </Tooltip>
              )}
              {a.edit && (
                <Button
                  type="link"
                  size="small"
                  onClick={() => setDialog({ type: 'form', item: r })}
                >
                  编辑
                </Button>
              )}
              {a.toggle && (
                <Button
                  type="link"
                  size="small"
                  onClick={() => toggle(r, a.toggle === 'disable' ? 'disabled' : 'enabled')}
                >
                  {a.toggle === 'disable' ? '停用' : '启用'}
                </Button>
              )}
              {a.regenerate && (
                <Button type="link" size="small" onClick={() => regenerate(r)}>
                  重新生成
                </Button>
              )}
              {a.remove && (
                <Button type="link" size="small" danger onClick={() => remove(r)}>
                  删除
                </Button>
              )}
            </Access>
            <Access code="openapi:log:list">
              <Button
                type="link"
                size="small"
                onClick={() => navigate(`/openapi/logs?api_key_id=${r.id}`)}
              >
                日志
              </Button>
            </Access>
          </Space>
        );
      },
    },
  ];

  return (
    <>
      <ProTable<ApiKeyItem, Filters>
        onRequestError={() => undefined}
        headerTitle="我的 API 密钥"
        rowKey="id"
        actionRef={actionRef}
        columns={columns}
        scroll={{ x: 1500 }}
        pagination={{ defaultPageSize: 20, showSizeChanger: false }}
        search={{ labelWidth: 'auto', defaultCollapsed: false }}
        locale={
          locale ?? {
            emptyText: '还没有 API 密钥。点击右上角“新建密钥”，创建后即可用它调用开放检索接口',
          }
        }
        request={wrap(async (params: Filters & { current?: number; pageSize?: number }) => {
          const res = await apiKeyApi.list({
            page: params.current ?? 1,
            page_size: params.pageSize ?? 20,
            name: params.name?.trim() || undefined,
            status: params.status || undefined,
          });
          return { data: res.items, total: res.total, success: true };
        })}
        toolBarRender={() => [
          <Access key="create" code="openapi:apikey:manage">
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setDialog({ type: 'form' })}
            >
              新建密钥
            </Button>
          </Access>,
        ]}
      />
      {dialog?.type === 'form' && (
        <ApiKeyFormModal
          item={dialog.item}
          onClose={() => setDialog(null)}
          onSaved={(res) => {
            setDialog(null);
            if (res) showSecret('密钥创建成功', res);
            reload();
          }}
        />
      )}
      {dialog?.type === 'accessible' && (
        <AccessibleDatasetsModal
          keyId={dialog.item.id}
          keyName={dialog.item.name}
          onClose={() => setDialog(null)}
        />
      )}
      {secret && (
        <ApiKeySecretModal
          title={secret.title}
          keyName={secret.name}
          secret={secret.secret}
          onClose={() => setSecret(null)}
        />
      )}
    </>
  );
}
