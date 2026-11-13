import type { ActionType } from '@ant-design/pro-components';
import { useCallback, useState, type MutableRefObject } from 'react';
import TableErrorState from '@/components/TableErrorState';
import { runListRequest, type ListResult } from '@/utils/listRequest';

/**
 * ProTable 错误状态：用 `wrap` 包装 request，失败时清空数据并通过 `locale` 显示错误占位 + 重试。
 * 用法：`request={wrap(async (params) => ...)}`、`locale={locale}`
 */
export function useTableError(actionRef: MutableRefObject<ActionType | undefined>) {
  const [error, setError] = useState<Error | null>(null);

  const wrap = useCallback(
    <P, T>(fn: (params: P) => Promise<ListResult<T>>) =>
      (params: P) =>
        runListRequest(() => fn(params), setError),
    [],
  );

  const locale = error
    ? {
        emptyText: (
          <TableErrorState message={error.message} onRetry={() => actionRef.current?.reload()} />
        ),
      }
    : undefined;

  return { wrap, locale, error };
}
