import { TreeSelect } from 'antd';
import { useMemo } from 'react';
import { useOrgOptions } from '@/hooks/useOrgOptions';
import type { OrgOption } from '@/services/types/iam-contract';
import { isManageable } from '@/utils/orgTree';

interface TreeDatum {
  value: number;
  title: string;
  disabled?: boolean;
  children?: TreeDatum[];
}

function toTreeData(nodes: OrgOption[], isDisabled?: (n: OrgOption) => boolean): TreeDatum[] {
  return nodes.map((n) => ({
    value: n.id,
    title: n.status === 'disabled' ? `${n.name}（已停用）` : n.name,
    disabled: isDisabled?.(n),
    children: toTreeData(n.children ?? [], isDisabled),
  }));
}

interface Props {
  /** 逗号分隔：group,company,dept，透传 5.2.2 */
  types?: string;
  multiple?: boolean;
  value?: number | number[];
  onChange?: (value: number | number[] | undefined) => void;
  /** 返回 true 的节点置灰不可选（如移动时的自身与后代） */
  isDisabled?: (n: OrgOption) => boolean;
  /** 用作写入目标时置灰 manageable=false 的节点（契约 5.2.0a） */
  disableUnmanageable?: boolean;
  placeholder?: string;
  allowClear?: boolean;
  disabled?: boolean;
  style?: React.CSSProperties;
}

export default function OrgTreeSelect({
  types,
  multiple,
  value,
  onChange,
  isDisabled,
  disableUnmanageable,
  placeholder = '请选择组织',
  allowClear = true,
  disabled,
  style,
}: Props) {
  const { data, isLoading, isError, refetch } = useOrgOptions({ types });
  const treeData = useMemo(
    () =>
      toTreeData(data ?? [], (n) => (disableUnmanageable && !isManageable(n)) || !!isDisabled?.(n)),
    [data, isDisabled, disableUnmanageable],
  );
  return (
    <TreeSelect
      style={{ width: '100%', ...style }}
      treeData={treeData}
      value={value}
      onChange={onChange}
      multiple={multiple}
      treeCheckable={false}
      loading={isLoading}
      status={isError ? 'error' : undefined}
      placeholder={isError ? '加载失败，点击重试' : placeholder}
      onDropdownVisibleChange={(open) => {
        if (open && isError) void refetch();
      }}
      allowClear={allowClear}
      disabled={disabled}
      showSearch
      treeNodeFilterProp="title"
      treeDefaultExpandAll
      notFoundContent="暂无可选组织"
    />
  );
}
