import { useSearchParams } from 'react-router-dom';
import CallLogTable from '@/components/CallLogTable';
import { parseApiKeyIdParam } from '@/components/callLog';

/** 调用日志（本人，F-19）；支持 ?api_key_id= 预填密钥 */
export default function CallLogPage() {
  const [params] = useSearchParams();
  const apiKeyId = parseApiKeyIdParam(params.get('api_key_id'));
  return (
    <CallLogTable key={apiKeyId ?? 'all'} mode="mine" apiKeyId={apiKeyId} headerTitle="调用日志" />
  );
}
