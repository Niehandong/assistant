import type { UserImpact } from '@/services/types/iam-contract';

/** 停用/删除前的影响提示文案（契约 5.3.9） */
export function describeImpact(impact: UserImpact | null): string {
  if (!impact || impact.degraded || impact.owned_dataset_count === null) {
    return '知识库数量暂无法获取，请确认其名下知识库已转移；其 API 密钥将失效。';
  }
  return `该用户拥有 ${impact.owned_dataset_count} 个知识库，请及时转移；其 API 密钥将失效。`;
}
