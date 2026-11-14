/**
 * B 端认证状态（Zustand）。Access Token 只存内存，不落 localStorage。
 *
 * 字段与后端登录响应（API §14.14）一一对应：
 *   `{ id, username, real_name, roles: [{id, code, name}] }`
 *
 * **不缓存 permissions 列表**：权限项由后端校验（M15-T05），
 * 前端只据此做「按钮显隐」之类体验优化。缓存一份完整权限列表会带来
 * 「前端说能点、后端说没权限」的不一致；需要时按需向后端查。
 */
import { create } from 'zustand';

export interface AdminRole {
  id: string;
  code: string;
  name: string;
}

export interface AdminUser {
  id: string;
  username: string;
  real_name: string | null;
  roles: AdminRole[];
}

interface AdminAuthState {
  accessToken: string | null;
  admin: AdminUser | null;
  /** 是否已完成启动时的会话恢复检查 */
  hydrated: boolean;

  setSession: (token: string, admin: AdminUser) => void;
  setAccessToken: (token: string) => void;
  setHydrated: (value: boolean) => void;
  clear: () => void;

  isAuthenticated: () => boolean;
  /** 是否持有某个角色 */
  hasRole: (code: string) => boolean;
  /** 是否超级管理员（拥有全部权限） */
  isSuperAdmin: () => boolean;
}

export const useAdminAuthStore = create<AdminAuthState>((set, get) => ({
  accessToken: null,
  admin: null,
  hydrated: false,

  setSession: (token, admin) => set({ accessToken: token, admin }),
  setAccessToken: (token) => set({ accessToken: token }),
  setHydrated: (value) => set({ hydrated: value }),
  clear: () => set({ accessToken: null, admin: null }),

  isAuthenticated: () => Boolean(get().accessToken),

  hasRole: (code) => {
    const admin = get().admin;
    if (!admin) return false;
    return admin.roles.some((role) => role.code === code);
  },

  isSuperAdmin: () => get().hasRole('super_admin'),
}));
