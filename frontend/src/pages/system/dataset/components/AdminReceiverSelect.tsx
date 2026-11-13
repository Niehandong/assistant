import { useQuery } from '@tanstack/react-query';
import { Select } from 'antd';
import { debounce } from 'lodash-es';
import { useMemo, useState } from 'react';
import { adminDatasetApi } from '@/services/kb';

interface Props {
  value?: number | null;
  onChange?: (value: number | null) => void;
  disabled?: boolean;
}

/** 远程搜索可接收人（admin/receivers：数据范围内、启用且未删除的用户） */
export default function AdminReceiverSelect({ value, onChange, disabled }: Props) {
  const [keyword, setKeyword] = useState('');
  const search = useMemo(() => debounce((v: string) => setKeyword(v.trim()), 300), []);
  const { data, isFetching } = useQuery({
    queryKey: ['kb-admin-receivers', keyword],
    queryFn: () =>
      adminDatasetApi.receivers({ keyword: keyword || undefined, page: 1, page_size: 20 }),
    staleTime: 30_000,
  });
  const options = (data?.items ?? []).map((u) => ({
    value: u.id,
    label: `${u.name}（${u.username}）${u.org_name ? ` · ${u.org_name}` : ''}`,
  }));
  return (
    <Select
      aria-label="接收人"
      showSearch
      allowClear
      filterOption={false}
      value={value ?? undefined}
      onChange={(v) => onChange?.(v ?? null)}
      onSearch={search}
      options={options}
      loading={isFetching}
      disabled={disabled}
      placeholder="输入姓名或账号搜索"
      notFoundContent={isFetching ? '搜索中' : '无匹配用户'}
    />
  );
}
