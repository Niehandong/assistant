import type { ProColumns } from '@ant-design/pro-components';
import { defaultRange, isDateDisabled } from './timeRange';

/** 日志页公共的时间范围搜索项：默认近 7 天、最长 180 天、不可选未来 */
export function timeRangeColumn<T>(): ProColumns<T> {
  return {
    title: '时间范围',
    dataIndex: 'time_range',
    valueType: 'dateTimeRange',
    hideInTable: true,
    colSize: 1.6,
    initialValue: defaultRange(),
    fieldProps: {
      allowClear: false,
      disabledDate: (
        current: Parameters<typeof isDateDisabled>[0],
        info?: { from?: Parameters<typeof isDateDisabled>[1] },
      ) => isDateDisabled(current, info?.from),
    },
    formItemProps: { rules: [{ required: true, message: '请选择时间范围' }] },
  };
}
