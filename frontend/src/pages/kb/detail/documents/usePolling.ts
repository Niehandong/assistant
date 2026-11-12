import { useEffect, useRef } from 'react';
import { documentApi } from '@/services/kb';
import type { DocumentProgressItem } from '@/services/types/kb-contract';
import { POLL_INTERVAL_MS, chunkIds } from './logic';

/**
 * 轮询文档进度：ids 非空时每 3 秒请求 progress，把结果交给 onResult；ids 为空（全部终态）自动停止。
 * 单次失败静默跳过，下个周期继续。
 */
export function useProgressPolling(
  datasetId: number,
  ids: number[],
  onResult: (items: DocumentProgressItem[]) => void,
  intervalMs = POLL_INTERVAL_MS,
) {
  const idsKey = ids.join(',');
  const onResultRef = useRef(onResult);
  useEffect(() => {
    onResultRef.current = onResult;
  });

  useEffect(() => {
    if (!idsKey) return;
    const list = idsKey.split(',').map(Number);
    let stopped = false;
    const timer = setInterval(() => {
      void (async () => {
        try {
          const results = await Promise.all(
            chunkIds(list).map((batch) => documentApi.progress(datasetId, batch)),
          );
          if (!stopped) onResultRef.current(results.flat());
        } catch {
          // 轮询失败不打扰用户，下个周期重试
        }
      })();
    }, intervalMs);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [datasetId, idsKey, intervalMs]);
}
