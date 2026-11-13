import { useQuery } from '@tanstack/react-query';
import { Select } from 'antd';
import { debounce } from 'lodash-es';
import { useMemo, useState } from 'react';
import { assignmentApi } from '@/services/kb';

interface Props {
  datasetId: number;
  value?: number | null;
  onChange?: (value: number | null) => void;
  placeholder?: string;
  disabled?: boolean;
}

/** 远程搜索“可分配/可转移”的用户（5.3 assignable-users：姓名/账号模糊，启用且在所有者可分配范围内） */
export default function AssignableUserSelect({
  datasetId,
  value,
  onChange,
  placeholder = '输入姓名或账号搜索',
  disabled,
}: Props) {
  const [keyword, setKeyword] = useState('');
  const search = useMemo(() => debounce((v: string) => setKeyword(v.trim()), 300), []);
  const { data, isFetching } = useQuery({
    queryKey: ['kb-assignable-users', datasetId, keyword],
    queryFn: () =>
      assignmentApi.assignableUsers(datasetId, {
        keyword: keyword || undefined,
        page: 1,
        page_size: 20,
      }),
    staleTime: 30_000,
  });
  const options = (data?.items ?? []).map((u) => ({
    value: u.id,
    label: `${u.name}（${u.username}）${u.org_name ? ` · ${u.org_name}` : ''}`,
  }));
  return (
    <Select
      showSearch
      allowClear
      filterOption={false}
      value={value ?? undefined}
      onChange={(v) => onChange?.(v ?? null)}
      onSearch={search}
      options={options}
      loading={isFetching}
      placeholder={placeholder}
      disabled={disabled}
      notFoundContent={isFetching ? '搜索中' : '无匹配用户'}
    />
  );
}
