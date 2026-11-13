import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useOutletContext } from 'react-router-dom';
import { datasetApi } from '@/services/kb';
import type { DatasetDetail } from '@/services/types/kb-contract';

export const datasetDetailKey = (id: number) => ['kb-dataset-detail', id] as const;

/** 知识库详情（所有子页面共享缓存） */
export function useDatasetQuery(id: number) {
  return useQuery({
    queryKey: datasetDetailKey(id),
    queryFn: () => datasetApi.detail(id),
    enabled: Number.isFinite(id),
  });
}

export interface DatasetOutletContext {
  dataset: DatasetDetail;
}

/** 子页面读取 Layout 已加载的知识库详情 */
export function useDataset(): DatasetDetail {
  return useOutletContext<DatasetOutletContext>().dataset;
}

/** 刷新详情缓存（保存设置、文档数变化后调用） */
export function useRefreshDataset(id: number) {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: datasetDetailKey(id) });
}
