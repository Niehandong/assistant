/** 登录后回跳地址安全校验：只允许站内绝对路径，避免开放重定向与回跳登录页 */
export function safeRedirect(raw: string | null | undefined, fallback = '/'): string {
  if (!raw) return fallback;
  let path = raw;
  try {
    path = decodeURIComponent(raw);
  } catch {
    return fallback;
  }
  if (!path.startsWith('/') || path.startsWith('//') || path.startsWith('/\\')) return fallback;
  if (path === '/login' || path.startsWith('/login?') || path.startsWith('/login#'))
    return fallback;
  return path;
}
