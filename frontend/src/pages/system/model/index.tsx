import { PlusOutlined } from '@ant-design/icons';
import { ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components';
import { App, Button, Space, Tag } from 'antd';
import { useRef, useState } from 'react';
import { Access } from '@/access/Access';
import { useTableError } from '@/hooks/useTableError';
import { modelApi } from '@/services/kb';
import { KbErrorCode, type ModelItem } from '@/services/types/kb-contract';
import { isApiError } from '@/utils/error';
import { formatDateTime } from '@/utils/format';
import { notifyError } from '@/utils/notify';
import ModelFormModal from './components/ModelFormModal';
import { MODEL_TYPE_LABEL, describeInUse, isInUseData } from './logic';

type Dialog = { type: 'form'; model?: ModelItem } | null;

export default function ModelPage() {
  const actionRef = useRef<ActionType>();
  const { wrap, locale } = useTableError(actionRef);
  const { modal, message } = App.useApp();
  const [dialog, setDialog] = useState<Dialog>(null);
  const reload = () => actionRef.current?.reload();

  /** 统一处理 409302 / 400301 等业务错误 */
  const handleOpError = (err: unknown) => {
    if (isApiError(err)) {
      if (err.code === KbErrorCode.MODEL_IN_USE_DELETE && isInUseData(err.data)) {
        modal.error({
          title: err.message,
          content: `引用的知识库：${describeInUse(err.data)}`,
        });
        return;
      }
      if (err.code === KbErrorCode.MODEL_TEST_FAILED) {
        const reason = (err.data as { error_message?: string } | null)?.error_message;
        modal.error({ title: err.message, content: reason ?? '请检查服务地址、模型标识与凭据' });
        return;
      }
    }
    notifyError(err);
  };

  const toggleStatus = (m: ModelItem) => {
    const enabling = m.status !== 'enabled';
    const run = async () => {
      try {
        await modelApi.setStatus(m.id, {
          status: enabling ? 'enabled' : 'disabled',
          version: m.version,
        });
        void message.success(enabling ? '已启用' : '已停用');
        reload();
      } catch (err) {
        handleOpError(err);
        reload();
      }
    };
    if (enabling) {
      void run();
      return;
    }
    modal.confirm({
      title: `确认停用模型「${m.name}」？`,
      content:
        m.model_type === 'embedding' && m.dataset_count > 0
          ? `有 ${m.dataset_count} 个知识库正在使用该模型，停用后这些知识库不能上传新文档、不能检索。`
          : m.model_type === 'rerank' && m.dataset_count > 0
            ? '停用后，开启了 Rerank 的检索将自动降级为不重排。'
            : '停用后新建知识库将无法选择该模型。',
      okText: '停用',
      okButtonProps: { danger: true },
      onOk: run,
    });
  };

  const setDefault = async (m: ModelItem) => {
    try {
      await modelApi.setDefault(m.id, { version: m.version });
      void message.success('已设为默认模型');
      reload();
    } catch (err) {
      notifyError(err);
      reload();
    }
  };

  const remove = (m: ModelItem) =>
    modal.confirm({
      title: `确认删除模型「${m.name}」？`,
      content: '删除后不可恢复；被知识库使用的模型无法删除。',
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await modelApi.remove(m.id);
          void message.success('已删除');
          reload();
        } catch (err) {
          handleOpError(err);
        }
      },
    });

  const columns: ProColumns<ModelItem>[] = [
    {
      title: '关键字',
      dataIndex: 'keyword',
      hideInTable: true,
      fieldProps: { placeholder: '名称或模型标识' },
    },
    { title: '名称', dataIndex: 'name', search: false, width: 160, ellipsis: true },
    {
      title: '类型',
      dataIndex: 'model_type',
      valueType: 'select',
      valueEnum: {
        embedding: { text: MODEL_TYPE_LABEL.embedding },
        rerank: { text: MODEL_TYPE_LABEL.rerank },
      },
      width: 130,
      render: (_, r) => (
        <Tag color={r.model_type === 'embedding' ? 'blue' : 'purple'}>
          {r.model_type === 'embedding' ? 'Embedding' : 'Rerank'}
        </Tag>
      ),
    },
    { title: '模型标识', dataIndex: 'model_name', search: false, width: 160, ellipsis: true },
    { title: '服务地址', dataIndex: 'base_url', search: false, width: 220, ellipsis: true },
    {
      title: '维度',
      dataIndex: 'dimension',
      search: false,
      width: 70,
      renderText: (v: number | null) => v ?? '-',
    },
    {
      title: '默认',
      dataIndex: 'is_default',
      search: false,
      width: 70,
      render: (_, r) => (r.is_default ? <Tag color="gold">默认</Tag> : '-'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      valueType: 'select',
      valueEnum: { enabled: { text: '启用' }, disabled: { text: '停用' } },
      width: 80,
      render: (_, r) => (
        <Tag color={r.status === 'enabled' ? 'success' : 'default'}>
          {r.status === 'enabled' ? '启用' : '停用'}
        </Tag>
      ),
    },
    {
      title: '引用知识库数',
      dataIndex: 'dataset_count',
      search: false,
      width: 110,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      search: false,
      width: 170,
      renderText: (v: string) => formatDateTime(v),
    },
    {
      title: '操作',
      valueType: 'option',
      fixed: 'right',
      width: 220,
      render: (_, r) => (
        <Space size={0} wrap>
          <Access code="system:model:update">
            <Button type="link" size="small" onClick={() => setDialog({ type: 'form', model: r })}>
              编辑
            </Button>
            <Button type="link" size="small" onClick={() => toggleStatus(r)}>
              {r.status === 'enabled' ? '停用' : '启用'}
            </Button>
            {r.status === 'enabled' && !r.is_default && (
              <Button type="link" size="small" onClick={() => setDefault(r)}>
                设为默认
              </Button>
            )}
          </Access>
          <Access code="system:model:delete">
            <Button type="link" size="small" danger onClick={() => remove(r)}>
              删除
            </Button>
          </Access>
        </Space>
      ),
    },
  ];

  return (
    <>
      <ProTable<ModelItem>
        onRequestError={() => undefined}
        headerTitle="模型配置"
        rowKey="id"
        actionRef={actionRef}
        columns={columns}
        scroll={{ x: 1300 }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        locale={locale}
        request={wrap(async (params) => {
          const res = await modelApi.list({
            page: params.current,
            page_size: params.pageSize,
            keyword: params.keyword || undefined,
            model_type: params.model_type || undefined,
            status: params.status || undefined,
          });
          return { data: res.items, total: res.total, success: true };
        })}
        toolBarRender={() => [
          <Access key="create" code="system:model:create">
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setDialog({ type: 'form' })}
            >
              新增模型
            </Button>
          </Access>,
        ]}
      />
      {dialog?.type === 'form' && (
        <ModelFormModal
          editing={dialog.model}
          onClose={() => setDialog(null)}
          onSuccess={() => {
            setDialog(null);
            reload();
          }}
        />
      )}
    </>
  );
}
