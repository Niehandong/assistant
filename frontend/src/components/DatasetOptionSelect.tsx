import { useQuery } from '@tanstack/react-query';
import { Select } from 'antd';
import { debounce } from 'lodash-es';
import { useMemo, useState } from 'react';
import { datasetApi } from '@/services/kb';

interface Props {
  value?: number | number[] | null;
  onChange?: (value: never) => void;
  multiple?: boolean;
  /** 已知名称（编辑回显）：不在搜索结果里的已选项用它显示，缺失显示"知识库 #id" */
  knownLabels?: Record<number, string>;
  /** 返回提示文案的已选项会追加到名称后（如"当前不可访问"） */
  isStale?: (id: number) => boolean;
  placeholder?: string;
  disabled?: boolean;
  style?: React.CSSProperties;
}

/** 远程搜索"我能访问的知识库"（kb 5.2.2），用于 API 密钥指定范围与调用日志筛选 */
export default function DatasetOptionSelect({
  value,
  onChange,
  multiple,
  knownLabels,
  isStale,
  placeholder = '输入名称搜索知识库',
  disabled,
  style,
}: Props) {
  const [keyword, setKeyword] = useState('');
  const search = useMemo(() => debounce((v: string) => setKeyword(v.trim()), 300), []);
  const { data, isFetching, isError } = useQuery({
    queryKey: ['kb-dataset-options', keyword],
    queryFn: () => datasetApi.options({ keyword: keyword || undefined, page: 1, page_size: 50 }),
    staleTime: 30_000,
  });

  const options = useMemo(() => {
    const list = (data?.items ?? []).map((d) => ({ value: d.id, label: d.name }));
    const selected = value == null ? [] : Array.isArray(value) ? value : [value];
    for (const id of selected) {
      if (!list.some((o) => o.value === id)) {
        list.unshift({ value: id, label: knownLabels?.[id] ?? `知识库 #${id}` });
      }
    }
    return list.map((o) => ({
      ...o,
      label: isStale?.(o.value) ? `${o.label}（当前不可访问）` : o.label,
    }));
  }, [data, value, knownLabels, isStale]);

  return (
    <Select
      mode={multiple ? 'multiple' : undefined}
      showSearch
      allowClear
      filterOption={false}
      value={value ?? undefined}
      onChange={onChange as (v: unknown) => void}
      onSearch={search}
      options={options}
      loading={isFetching}
      placeholder={placeholder}
      disabled={disabled}
      maxTagCount="responsive"
      style={{ width: '100%', ...style }}
      notFoundContent={isFetching ? '搜索中' : isError ? '知识库列表加载失败' : '没有可选的知识库'}
    />
  );
}
