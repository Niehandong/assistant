/** 新密码规则（PRD F-01 规则 7 / 契约 5.1.5）：8~32 位、同时含字母和数字、不同于旧密码。返回 null 表示通过 */
export function validateNewPassword(newPassword: string, oldPassword?: string): string | null {
  if (newPassword.length < 8 || newPassword.length > 32) return '密码长度须为 8~32 位';
  if (!/[A-Za-z]/.test(newPassword)) return '密码必须包含字母';
  if (!/\d/.test(newPassword)) return '密码必须包含数字';
  if (oldPassword !== undefined && newPassword === oldPassword) return '新密码不能与当前密码相同';
  return null;
}
