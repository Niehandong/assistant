import { useQuery } from '@tanstack/react-query';
import { Drawer, Skeleton } from 'antd';
import CallLogTable from '@/components/CallLogTable';
import { auditApi } from '@/services/open';

interface Props {
  /** 指定则只看该密钥的日志；缺省为"全部调用日志" */
  apiKey?: { id: number; name: string } | null;
  onClose: () => void;
}

/** 审计调用日志抽屉（只读） */
export default function AuditCallLogDrawer({ apiKey, onClose }: Props) {
  // 仅"全部调用日志"需要查询能力；失败或 false 时不显示开关也不传 include_unknown
  const caps = useQuery({
    queryKey: ['open-audit-capabilities'],
    queryFn: () => auditApi.capabilities(),
    enabled: !apiKey,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });
  const canViewUnknown = !apiKey && caps.data?.can_view_unknown_calls === true;
  const waiting = !apiKey && caps.isLoading;

  return (
    <Drawer
      open
      width="80%"
      destroyOnClose
      title={apiKey ? `「${apiKey.name}」的调用日志` : '全部调用日志'}
      onClose={onClose}
    >
      {waiting ? (
        <Skeleton active />
      ) : (
        <CallLogTable mode="audit" apiKeyId={apiKey?.id} showUnknownSwitch={canViewUnknown} />
      )}
    </Drawer>
  );
}
