/** 硬跳转封装（便于单测 mock）。硬跳转同时清空内存态。 */
export function currentLocation(): string {
  return window.location.pathname + window.location.search + window.location.hash;
}

export function redirectToLogin(): void {
  const { pathname } = window.location;
  if (pathname === '/login') return;
  const redirect = encodeURIComponent(currentLocation());
  window.location.assign(`/login?redirect=${redirect}`);
}

export function redirectToChangePassword(): void {
  if (window.location.pathname === '/change-password') return;
  window.location.assign('/change-password');
}
