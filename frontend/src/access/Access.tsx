import type { ReactNode } from 'react';
import { usePermission, type PermissionMode } from './usePermission';

interface AccessProps {
  code: string | readonly string[];
  mode?: PermissionMode;
  /** 无权限时渲染的内容，默认不渲染 */
  fallback?: ReactNode;
  children: ReactNode;
}

export function Access({ code, mode = 'any', fallback = null, children }: AccessProps) {
  const can = usePermission();
  return <>{can(code, mode) ? children : fallback}</>;
}
