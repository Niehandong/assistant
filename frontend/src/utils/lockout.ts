import { ApiError } from './error';

/** 409124：保存后将失去页面权限（需确认） */
export const SELF_LOCKOUT_CODE = 409124;

export const SELF_LOCKOUT_PERMISSION_LABELS: Record<string, string> = {
  'system:user:list': '用户管理',
  'system:role:list': '角色管理',
};

/** 把 409124 的 data.lost_permissions 转成给用户看的页面名 */
export function describeLostPermissions(err: ApiError): string {
  const lost = (err.data as { lost_permissions?: string[] } | null)?.lost_permissions ?? [];
  const names = lost.map((c) => SELF_LOCKOUT_PERMISSION_LABELS[c] ?? c);
  return names.length > 0
    ? `保存后您将失去「${names.join('、')}」页面权限，是否继续？`
    : '保存后您将失去该页面权限，是否继续？';
}

/** 用户取消二次确认时抛出，调用方应静默处理 */
export class LockoutCancelled extends Error {
  constructor() {
    super('已取消');
    this.name = 'LockoutCancelled';
  }
}

/**
 * 提交；若后端返回 409124 则弹出二次确认，确认后带 confirm_self_lockout=true 重提一次。
 * 取消确认抛 LockoutCancelled；其他错误原样抛出。
 */
export async function submitWithLockoutConfirm<T>(
  submit: (confirmSelfLockout: boolean) => Promise<T>,
  confirm: (message: string, err: ApiError) => Promise<boolean>,
): Promise<T> {
  try {
    return await submit(false);
  } catch (err) {
    if (err instanceof ApiError && err.code === SELF_LOCKOUT_CODE) {
      const ok = await confirm(describeLostPermissions(err), err);
      if (!ok) throw new LockoutCancelled();
      return submit(true);
    }
    throw err;
  }
}
