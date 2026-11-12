import { PlusOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Card,
  Empty,
  Flex,
  Input,
  Pagination,
  Result,
  Select,
  Skeleton,
  Space,
  Tag,
  Typography,
} from 'antd';
import { useRef, useState } from 'react';
import type { PageResult, SegmentItem, SegmentListQuery } from '@/services/types/kb-contract';
import { getErrorMessage } from '@/utils/error';
import { formatNumber } from '@/utils/format';
import { CHUNK_MODE_LABEL } from '../../../list/logic';
import {
  SEGMENT_PAGE_SIZE,
  SEGMENT_POLL_INTERVAL_MS,
  buildSegmentQuery,
  contentLimit,
  needsPolling,
  type SegmentDocInfo,
} from '../logic';
import { useSegmentActions } from '../useSegmentActions';
import ChildChunkEditor from './ChildChunkEditor';
import SegmentDrawer from './SegmentDrawer';
import SegmentList from './SegmentList';

interface Props {
  datasetId: number;
  doc: SegmentDocInfo;
  /** 只读模式（管理视图复用）：无新增/编辑/启停/删除入口，不轮询 */
  readonly: boolean;
  /** 在非只读模式下，当前用户是否可编辑（权限码 + ACL + 文档状态） */
  canEdit: boolean;
  /** 不可编辑但非只读模式时的原因提示 */
  disabledReason?: string | null;
  fetchSegments: (params: SegmentListQuery) => Promise<PageResult<SegmentItem>>;
  /** 区分普通/管理视图的缓存与失效范围 */
  scope: 'normal' | 'admin';
}

type DrawerState = { seg: SegmentItem | null; mode: 'view' | 'edit' | 'create' } | null;
type ChildState = { seg: SegmentItem; childId: number | null } | null;

/** 文档分段面板：FE-13 页面与 FE-17 管理视图共用 */
export default function SegmentsPanel({
  datasetId,
  doc,
  readonly,
  canEdit,
  disabledReason,
  fetchSegments,
  scope,
}: Props) {
  const [filters, setFilters] = useState<{ keyword?: string; enabled?: 'true' | 'false' }>({});
  const [page, setPage] = useState(1);
  const [drawer, setDrawer] = useState<DrawerState>(null);
  const [childEditor, setChildEditor] = useState<ChildState>(null);
  // 面板每次挂载（打开分段列表）视为一次主动进入
  const entryRef = useRef(true);
  const actions = useSegmentActions(datasetId, doc.id);
  const editable = !readonly && canEdit;
  const parentChild = doc.chunk_mode === 'parent_child';

  const query = buildSegmentQuery(filters, page);
  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['kb-segments', scope, datasetId, doc.id, query],
    queryFn: async () => {
      // 管理视图：仅“主动进入”的那次请求带 audit_entry（5.8.1）；翻页/搜索/重取不带
      const entry = scope === 'admin' && entryRef.current;
      const res = await fetchSegments(entry ? { ...query, audit_entry: true } : query);
      if (entry) entryRef.current = false;
      return res;
    },
    // 管理视图每次 page=1 请求都会写审计日志：不自动重取，避免重复记录
    refetchOnWindowFocus: !readonly,
    refetchInterval: (q) =>
      !readonly && q.state.data && needsPolling(q.state.data.items)
        ? SEGMENT_POLL_INTERVAL_MS
        : false,
  });
  const items = data?.items ?? [];
  const hasFilter = !!(filters.keyword?.trim() || filters.enabled);

  // 编辑抽屉中的分段取最新数据（刷新后 version 才会更新）
  const current = (seg: SegmentItem | null) =>
    seg ? (items.find((i) => i.id === seg.id) ?? seg) : null;
  const editingSeg = current(drawer?.seg ?? null);
  const childSeg = childEditor ? current(childEditor.seg) : null;
  const editingChild = childSeg?.children.find((c) => c.id === childEditor?.childId) ?? null;

  const rowActions = {
    canEdit: editable,
    busy: actions.busy,
    onView: (seg: SegmentItem) => setDrawer({ seg, mode: 'view' }),
    onEdit: (seg: SegmentItem) => setDrawer({ seg, mode: 'edit' }),
    onToggle: (seg: SegmentItem, v: boolean) => void actions.toggleEnabled(seg, v),
    onRemove: actions.removeSegment,
    onAddChild: (seg: SegmentItem) => setChildEditor({ seg, childId: null }),
    onEditChild: (seg: SegmentItem, childId: number) => setChildEditor({ seg, childId }),
    onRemoveChild: (seg: SegmentItem, childId: number) => {
      const c = seg.children.find((x) => x.id === childId);
      if (c) actions.removeChild(c);
    },
  };

  const drawerSeg = drawer?.mode === 'create' ? null : editingSeg;
  const drawerLimit = contentLimit(doc.process_rule, drawerSeg?.segment_type ?? 'general');

  let body;
  if (isLoading) {
    body = <Skeleton active paragraph={{ rows: 6 }} />;
  } else if (error && !data) {
    body = (
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
    );
  } else {
    body = (
      <>
        <SegmentList
          items={items}
          actions={rowActions}
          empty={
            <Empty
              description={
                hasFilter
                  ? '没有符合条件的分段'
                  : doc.status === 'available'
                    ? '该文档暂无分段'
                    : '文档尚未处理完成，暂无分段'
              }
            />
          }
        />
        {(data?.total ?? 0) > SEGMENT_PAGE_SIZE && (
          <Flex justify="end" style={{ marginTop: 16 }}>
            <Pagination
              current={page}
              pageSize={SEGMENT_PAGE_SIZE}
              total={data?.total ?? 0}
              showSizeChanger={false}
              onChange={setPage}
            />
          </Flex>
        )}
      </>
    );
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card size="small">
        <Flex justify="space-between" align="center" wrap="wrap" gap={12}>
          <Space size={12} wrap>
            <Typography.Title level={5} style={{ margin: 0 }}>
              {doc.name}
            </Typography.Title>
            <Tag color="geekblue">{CHUNK_MODE_LABEL[doc.chunk_mode]}</Tag>
            <Typography.Text type="secondary">
              {parentChild
                ? `父块 ${formatNumber(doc.segment_count)} / 子块 ${formatNumber(doc.child_count)}`
                : `${formatNumber(doc.segment_count)} 个分段`}
            </Typography.Text>
            <Typography.Text type="secondary">{formatNumber(doc.char_count)} 字符</Typography.Text>
          </Space>
          {editable && !parentChild && (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setDrawer({ seg: null, mode: 'create' })}
            >
              新增分段
            </Button>
          )}
        </Flex>
      </Card>
      {!readonly && disabledReason && <Alert type="warning" showIcon message={disabledReason} />}
      <Card size="small">
        <Flex gap={12} wrap="wrap" style={{ marginBottom: 16 }}>
          <Input.Search
            allowClear
            style={{ width: 280 }}
            placeholder={parentChild ? '按父块或子块内容搜索' : '按内容搜索'}
            onSearch={(v) => {
              setFilters((f) => ({ ...f, keyword: v }));
              setPage(1);
            }}
          />
          <Select
            allowClear
            style={{ width: 140 }}
            placeholder="启用状态"
            aria-label="启用状态"
            value={filters.enabled}
            options={[
              { value: 'true', label: '已启用' },
              { value: 'false', label: '已禁用' },
            ]}
            onChange={(v: 'true' | 'false' | undefined) => {
              setFilters((f) => ({ ...f, enabled: v }));
              setPage(1);
            }}
          />
          {isFetching && !isLoading && <Typography.Text type="secondary">刷新中…</Typography.Text>}
        </Flex>
        {body}
      </Card>
      {drawer && (
        <SegmentDrawer
          open
          segment={drawerSeg}
          readonly={readonly || drawer.mode === 'view' || !editable}
          limit={drawerLimit}
          onClose={() => setDrawer(null)}
          onSubmit={(form) =>
            drawerSeg ? actions.saveSegment(drawerSeg, form) : actions.createSegment(form)
          }
        />
      )}
      {childEditor && childSeg && (
        <ChildChunkEditor
          open
          child={editingChild}
          limit={contentLimit(doc.process_rule, 'child')}
          onClose={() => setChildEditor(null)}
          onSubmit={(content) =>
            editingChild
              ? actions.saveChild(editingChild, content)
              : actions.createChild(childSeg.id, content)
          }
        />
      )}
    </Space>
  );
}
