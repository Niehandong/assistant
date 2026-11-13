import { useQuery } from '@tanstack/react-query';
import { modelApi } from '@/services/kb';
import type { DatasetDetail } from '@/services/types/kb-contract';

/** 知识库所用 Embedding 模型的单次最大输入（模型已停用/不在启用选项中时返回 undefined，不做上限校验） */
export function useEmbeddingMaxTokens(dataset: Pick<DatasetDetail, 'embedding_model'>) {
  const { data } = useQuery({
    queryKey: ['kb-model-options', 'embedding'],
    queryFn: () => modelApi.options('embedding'),
    staleTime: 60_000,
  });
  return data?.find((m) => m.id === dataset.embedding_model.id)?.max_input_tokens;
}
