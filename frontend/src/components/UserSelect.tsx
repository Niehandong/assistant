import { useQuery } from '@tanstack/react-query';
import { Select } from 'antd';
import { debounce } from 'lodash-es';
import { useMemo, useState } from 'react';
import { userApi } from '@/services/iam';

interface Props {
  value?: number | null;
  onChange?: (value: number | null) => void;
  /** 已选用户的展示名（编辑回显用，避免搜索结果里没有该用户时显示成数字） */
  initialLabel?: string | null;
  placeholder?: string;
  disabled?: boolean;
}

/** 远程搜索用户（5.3.1，按姓名模糊） */
export default function UserSelect({
  value,
  onChange,
  initialLabel,
  placeholder = '输入姓名搜索',
  disabled,
}: Props) {
  const [keyword, setKeyword] = useState('');
  const search = useMemo(() => debounce((v: string) => setKeyword(v.trim()), 300), []);
  const { data, isFetching } = useQuery({
    queryKey: ['user-select', keyword],
    queryFn: () => userApi.list({ page: 1, page_size: 20, name: keyword || undefined }),
    staleTime: 30_000,
  });
  const options = (data?.items ?? []).map((u) => ({
    value: u.id,
    label: `${u.name}（${u.username}）`,
  }));
  if (value && initialLabel && !options.some((o) => o.value === value)) {
    options.unshift({ value, label: initialLabel });
  }
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
