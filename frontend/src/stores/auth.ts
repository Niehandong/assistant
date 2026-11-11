import { create } from 'zustand';
import { tokenStore } from '@/api/tokenStore';
import { authApi } from '@/services/iam';
import type { CurrentUser, MenuNode } from '@/services/types/iam-contract';

interface AuthState {
  user: CurrentUser | null;
  permissions: Set<string>;
  menus: MenuNode[];
  /** me 是否已成功加载 */
  loaded: boolean;
  loading: boolean;
  loadMe: () => Promise<void>;
  /** 登出：调用接口（失败忽略）、清 token、重置状态 */
  logout: () => Promise<void>;
  reset: () => void;
}

const initial = {
  user: null,
  permissions: new Set<string>(),
  menus: [] as MenuNode[],
  loaded: false,
  loading: false,
};

export const useAuthStore = create<AuthState>((set) => ({
  ...initial,
  async loadMe() {
    set({ loading: true });
    try {
      const me = await authApi.me();
      set({
        user: me.user,
        permissions: new Set(me.permissions),
        menus: me.menus,
        loaded: true,
        loading: false,
      });
    } catch (err) {
      set({ loading: false });
      throw err;
    }
  },
  async logout() {
    try {
      await authApi.logout();
    } catch {
      // 登出接口失败（如令牌已失效）不阻塞本地登出
    } finally {
      tokenStore.clear();
      set({ ...initial, permissions: new Set<string>() });
    }
  },
  reset() {
    tokenStore.clear();
    set({ ...initial, permissions: new Set<string>() });
  },
}));
