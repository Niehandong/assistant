import { useQuery } from '@tanstack/react-query';
import { orgApi } from '@/services/iam';

export const ORG_OPTIONS_KEY = 'org-options';

/** 组织选择器数据（5.2.2） */
export function useOrgOptions(params?: { types?: string; include_disabled?: boolean }) {
  return useQuery({
    queryKey: [ORG_OPTIONS_KEY, params?.types ?? '', params?.include_disabled ?? true],
    queryFn: () => orgApi.options(params),
    staleTime: 30_000,
  });
}
