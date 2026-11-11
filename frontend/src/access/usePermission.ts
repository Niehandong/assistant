import { useAuthStore } from '@/stores/auth';

export type PermissionMode = 'any' | 'all';

/** 纯函数：判断是否拥有权限码。超级管理员直接放行；空数组视为无需权限。 */
export function checkPermission(
  permissions: ReadonlySet<string>,
  isSuperAdmin: boolean,
  code: string | readonly string[],
  mode: PermissionMode = 'any',
): boolean {
  if (isSuperAdmin) return true;
  const codes = typeof code === 'string' ? [code] : code;
  if (codes.length === 0) return true;
  return mode === 'all'
    ? codes.every((c) => permissions.has(c))
    : codes.some((c) => permissions.has(c));
}

/** 用法：const can = usePermission(); can('system:user:create') / can([...], 'all') */
export function usePermission() {
  const permissions = useAuthStore((s) => s.permissions);
  const isSuper = useAuthStore((s) => s.user?.is_super_admin ?? false);
  return (code: string | readonly string[], mode: PermissionMode = 'any') =>
    checkPermission(permissions, isSuper, code, mode);
}
