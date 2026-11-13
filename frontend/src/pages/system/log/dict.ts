/** 操作日志枚举中文映射（契约 5.8）；未知值回退显示原值 */
export const MODULE_LABEL: Record<string, string> = {
  user: '用户',
  role: '角色',
  org: '组织',
  model: '模型',
  dataset: '知识库',
  document: '文档',
  api_key: 'API 密钥',
};

export const ACTION_LABEL: Record<string, Record<string, string>> = {
  user: {
    create: '新增',
    update: '编辑',
    status: '启停',
    reset_password: '重置密码',
    assign_role: '分配角色',
    delete: '删除',
  },
  role: { create: '新增', update: '编辑', grant: '授权', delete: '删除' },
  org: { create: '新增', update: '编辑', move: '移动', status: '启停', delete: '删除' },
  model: {
    create: '新增',
    update: '编辑',
    status: '启停',
    set_default: '设为默认',
    delete: '删除',
  },
  dataset: {
    create: '新增',
    update: '编辑',
    delete: '删除',
    assign_create: '新增分配',
    assign_update: '修改分配',
    assign_delete: '取消分配',
    transfer: '转移所有权',
    retrieval_config: '检索设置',
    admin_view: '管理员查看',
  },
  document: { upload: '上传', delete: '删除', reprocess: '重新处理' },
  api_key: {
    create: '新增',
    update: '编辑',
    status: '启停',
    regenerate: '重新生成',
    delete: '删除',
    admin_disable: '管理员停用',
    admin_delete: '管理员删除',
  },
};

export const RESULT_LABEL: Record<string, string> = { success: '成功', failure: '失败' };

/** 登录失败原因（契约 4.9 完整枚举） */
export const FAIL_REASON_LABEL: Record<string, string> = {
  bad_credentials: '账号或密码错误',
  locked: '账号已锁定',
  user_disabled: '账号已停用',
  org_disabled: '所属组织已停用',
};

export const moduleLabel = (m: string): string => MODULE_LABEL[m] ?? m;
export const actionLabel = (m: string, a: string): string => ACTION_LABEL[m]?.[a] ?? a;

export const MODULE_VALUE_ENUM = Object.fromEntries(
  Object.entries(MODULE_LABEL).map(([k, v]) => [k, { text: v }]),
);

/** 全部 action 去重后的下拉枚举（模块未选时使用） */
export const ALL_ACTION_VALUE_ENUM: Record<string, { text: string }> = (() => {
  const out: Record<string, { text: string }> = {};
  for (const [m, actions] of Object.entries(ACTION_LABEL)) {
    for (const [a, label] of Object.entries(actions)) {
      if (!out[a]) out[a] = { text: label };
      else if (out[a].text !== label) out[a] = { text: `${out[a].text}/${label}` };
      void m;
    }
  }
  return out;
})();
