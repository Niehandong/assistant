import { message } from 'antd';
import { LockoutCancelled } from './lockout';
import { getErrorMessage } from './error';

/** 表单类提交（skipErrorToast）失败时的统一提示；用户主动取消不提示 */
export function notifyError(err: unknown): void {
  if (err instanceof LockoutCancelled) return;
  void message.error(getErrorMessage(err));
}
