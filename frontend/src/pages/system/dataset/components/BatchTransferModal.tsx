import { useQuery } from '@tanstack/react-query';
import { Alert, App, Form, Modal, Select, Table, Typography } from 'antd';
import { debounce } from 'lodash-es';
import { useMemo, useState } from 'react';
import { adminDatasetApi } from '@/services/kb';
import type { AdminDatasetItem } from '@/services/types/kb-contract';
import { getErrorMessage } from '@/utils/error';
import {
  BATCH_DATASET_PAGE_SIZE,
  buildBatchBody,
  ownerStatusTag,
  parseTransferError,
  segmentText,
} from '../logic';
import AdminReceiverSelect from './AdminReceiverSelect';

interface Props {
  /** 预选的原所有者（如从“待交接”列表进入） */
  initialOwnerId?: number;
  onClose: () => void;
  onDone: () => void;
}

/** 批量转移（离职交接）：选原所有者 -> 勾选其名下知识库 -> 选接收人 -> 确认 */
export default function BatchTransferModal({ initialOwnerId, onClose, onDone }: Props) {
  const { message, modal } = App.useApp();
  const [ownerId, setOwnerId] = useState<number | undefined>(initialOwnerId);
  const [receiverId, setReceiverId] = useState<number | null>(null);
  const [picked, setPicked] = useState<number[] | null>(null);
  const [keyword, setKeyword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<{ message: string; conflicts: string[] } | null>(null);
  const search = useMemo(() => debounce((v: string) => setKeyword(v.trim()), 300), []);

  const owners = useQuery({
    queryKey: ['kb-admin-owners', keyword],
    queryFn: () => adminDatasetApi.owners({ keyword: keyword || undefined }),
    staleTime: 30_000,
  });
  const datasets = useQuery({
    queryKey: ['kb-admin-owner-datasets', ownerId],
    queryFn: () =>
      adminDatasetApi.list({ owner_id: ownerId, page: 1, page_size: BATCH_DATASET_PAGE_SIZE }),
    enabled: ownerId !== undefined,
  });
  const rows = datasets.data?.items ?? [];
  const total = datasets.data?.total ?? 0;
  // 默认全选；用户手动勾选后以勾选为准
  const selected = picked ?? rows.map((r) => r.id);
  const owner = owners.data?.find((o) => o.id === ownerId);

  const submit = () => {
    if (ownerId === undefined || receiverId === null || selected.length === 0) return;
    modal.confirm({
      title: '确认批量转移？',
      content: `将把 ${owner ? `${owner.name} ` : ''}名下 ${selected.length} 个知识库转移给所选接收人，原所有者将失去访问权限。`,
      okText: '确认转移',
      okButtonProps: { danger: true },
      onOk: async () => {
        setSubmitting(true);
        setError(null);
        try {
          const r = await adminDatasetApi.batchTransfer(
            buildBatchBody({
              fromUserId: ownerId,
              receiverId,
              selectedIds: selected,
              loadedCount: rows.length,
              total,
            }),
          );
          void message.success(`已转移 ${r.transferred} 个知识库`);
          onDone();
          onClose();
        } catch (err) {
          setError(parseTransferError(err));
        } finally {
          setSubmitting(false);
        }
      },
    });
  };

  return (
    <Modal
      open
      title="批量转移知识库"
      width={720}
      maskClosable={false}
      onCancel={onClose}
      onOk={submit}
      okText="转移"
      okButtonProps={{
        danger: true,
        loading: submitting,
        disabled: ownerId === undefined || receiverId === null || selected.length === 0,
      }}
      destroyOnClose
    >
      <Form layout="vertical">
        <Form.Item label="原所有者" required>
          <Select
            aria-label="原所有者"
            showSearch
            filterOption={false}
            value={ownerId}
            loading={owners.isFetching}
            placeholder="输入姓名或账号搜索"
            onSearch={search}
            onChange={(v: number) => {
              setOwnerId(v);
              setPicked(null);
              setError(null);
            }}
            options={(owners.data ?? []).map((o) => ({
              value: o.id,
              label: `${o.name}（${o.username}）${ownerStatusTag(o.status) ? ` [${ownerStatusTag(o.status)}]` : ''} · ${o.dataset_count} 个知识库`,
            }))}
          />
        </Form.Item>
        {ownerId !== undefined && (
          <Form.Item label={`名下知识库（已选 ${selected.length}/${total}）`}>
            {datasets.error ? (
              <Alert type="error" showIcon message={getErrorMessage(datasets.error)} />
            ) : (
              <Table<AdminDatasetItem>
                size="small"
                rowKey="id"
                loading={datasets.isLoading}
                dataSource={rows}
                pagination={false}
                scroll={{ y: 220 }}
                locale={{ emptyText: '该用户在您的数据范围内没有知识库' }}
                rowSelection={{
                  selectedRowKeys: selected,
                  onChange: (keys) => setPicked(keys as number[]),
                }}
                columns={[
                  { title: '名称', dataIndex: 'name', ellipsis: true },
                  { title: '文档数', dataIndex: 'doc_count', width: 80 },
                  { title: '分段', width: 140, render: (_, r) => segmentText(r) },
                ]}
              />
            )}
            {total > rows.length && (
              <Typography.Text type="secondary">
                仅显示前 {rows.length} 个；未手动调整勾选时将转移其名下全部 {total} 个。
              </Typography.Text>
            )}
          </Form.Item>
        )}
        <Form.Item label="接收人" required extra="接收人名下不能有同名知识库">
          <AdminReceiverSelect value={receiverId} onChange={setReceiverId} />
        </Form.Item>
      </Form>
      {error && (
        <Alert
          type="error"
          showIcon
          message={error.message}
          description={
            error.conflicts.length > 0 ? (
              <div>
                同名冲突的知识库：
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {error.conflicts.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
                已整体回滚，请先改名后重试。
              </div>
            ) : undefined
          }
        />
      )}
    </Modal>
  );
}
