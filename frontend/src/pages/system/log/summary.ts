import { DATA_SCOPE_LABEL } from '@/pages/system/role/grantLogic';

export interface DiffRow {
  field: string;
  before: string;
  after: string;
}

export interface KvRow {
  field: string;
  value: string;
}

export type ParsedSummary =
  | { kind: 'empty' }
  | { kind: 'diff'; rows: DiffRow[]; extra?: KvRow[] }
  | { kind: 'kv'; rows: KvRow[] }
  | { kind: 'json'; text: string };

const FIELD_LABEL: Record<string, string> = {
  permissions: '权限',
  data_scope: '数据范围',
  custom_orgs: '自定义组织',
  roles: '角色',
  document_name: '文档名称',
  custom_role_refs_removed: '已移除引用的自定义范围角色',
  // 常见 before/after 字段
  name: '名称',
  code: '编码',
  username: '账号',
  status: '状态',
  remark: '备注',
  role_type: '角色类型',
  org_type: '组织类型',
  owner_company_id: '所属公司 ID',
  org_id: '所属组织 ID',
  parent_id: '上级组织 ID',
  sort_order: '显示顺序',
  leader_user_id: '负责人 ID',
  mobile: '手机号',
  email: '邮箱',
};

const VALUE_LABEL: Record<string, Record<string, string>> = {
  status: { enabled: '启用', disabled: '停用' },
  role_type: { group: '集团级', company: '公司级' },
  org_type: { group: '集团', company: '公司', dept: '部门' },
};

const label = (key: string): string => FIELD_LABEL[key] ?? key;

const show = (v: unknown, key?: string): string => {
  if (v === null || v === undefined || v === '') return '-';
  if (key === 'data_scope' && typeof v === 'string')
    return DATA_SCOPE_LABEL[v as keyof typeof DATA_SCOPE_LABEL] ?? v;
  if (key && typeof v === 'string' && VALUE_LABEL[key]) return VALUE_LABEL[key][v] ?? v;
  if (Array.isArray(v)) return v.length ? v.map(String).join('、') : '-';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
};

const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);

/**
 * 解析操作日志 summary（契约 5.8 结构约定）：
 * - 新建 `{after}`、删除 `{before}`（组织删除另含 `custom_role_refs_removed`）、编辑 `{before, after}` → 按字段逐行对比
 * - 授权：`permissions/custom_orgs` 的 added/removed，`data_scope` 的 before/after
 * - 分配角色：`{before:[角色名], after:[角色名]}`
 * - 审计查看：`{document_name}`
 * - 其他未知结构 → JSON 原样展示
 */
export function parseSummary(summary: unknown): ParsedSummary {
  if (summary === null || summary === undefined || summary === '') return { kind: 'empty' };
  const json = (): ParsedSummary => ({ kind: 'json', text: JSON.stringify(summary, null, 2) });
  if (!isObj(summary)) return json();
  const keys = Object.keys(summary);
  if (keys.length === 0) return { kind: 'empty' };

  // 审计查看
  if (keys.length === 1 && keys[0] === 'document_name') {
    return {
      kind: 'kv',
      rows: [{ field: label('document_name'), value: show(summary.document_name) }],
    };
  }

  // 顶层 before/after 为对象：新建（仅 after）、删除（仅 before）、编辑（两份）
  const OBJ_KEYS = ['before', 'after', 'custom_role_refs_removed'];
  if (keys.every((k) => OBJ_KEYS.includes(k)) && (isObj(summary.before) || isObj(summary.after))) {
    const b = isObj(summary.before) ? summary.before : {};
    const a = isObj(summary.after) ? summary.after : {};
    const fields = [...new Set([...Object.keys(b), ...Object.keys(a)])];
    const extra: KvRow[] = [];
    if ('custom_role_refs_removed' in summary) {
      extra.push({
        field: label('custom_role_refs_removed'),
        value: show(summary.custom_role_refs_removed),
      });
    }
    return {
      kind: 'diff',
      rows: fields.map((f) => ({ field: label(f), before: show(b[f], f), after: show(a[f], f) })),
      ...(extra.length ? { extra } : {}),
    };
  }

  // 分配角色：before/after 为数组
  if (keys.length === 2 && 'before' in summary && 'after' in summary) {
    return {
      kind: 'diff',
      rows: [{ field: label('roles'), before: show(summary.before), after: show(summary.after) }],
    };
  }

  // 授权等：子项含 before/after 或 added/removed
  const rows: DiffRow[] = [];
  for (const [key, val] of Object.entries(summary)) {
    if (isObj(val) && ('before' in val || 'after' in val)) {
      rows.push({ field: label(key), before: show(val.before, key), after: show(val.after, key) });
    } else if (isObj(val) && ('added' in val || 'removed' in val)) {
      rows.push({
        field: label(key),
        before: `移除：${show(val.removed)}`,
        after: `新增：${show(val.added)}`,
      });
    } else {
      return json();
    }
  }
  return rows.length > 0 ? { kind: 'diff', rows } : json();
}
