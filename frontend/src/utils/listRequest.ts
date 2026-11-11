export interface ListResult<T> {
  data: T[];
  success: boolean;
  total?: number;
}

/**
 * 列表请求包装：失败时不抛出、不保留旧数据——返回空数据并通知调用方记录错误，
 * 由页面渲染“加载失败 + 重试”占位（CLAUDE.md 第 6 节：错误状态）。
 */
export async function runListRequest<T>(
  fn: () => Promise<ListResult<T>>,
  onError: (err: Error | null) => void,
): Promise<ListResult<T>> {
  try {
    const res = await fn();
    onError(null);
    return res;
  } catch (err) {
    onError(err instanceof Error ? err : new Error('加载失败'));
    return { data: [], total: 0, success: true };
  }
}
