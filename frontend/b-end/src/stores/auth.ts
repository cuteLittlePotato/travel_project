/**
 * B 端认证状态（Zustand）。Access Token 只存内存，不落 localStorage。
 */
import { create } from 'zustand';

export interface AdminUser {
  admin_id: string;
  username: string;
  display_name: string;
  role: string;
  permissions: string[];
}

interface AdminAuthState {
  accessToken: string | null;
  admin: AdminUser | null;
  setSession: (token: string, admin: AdminUser) => void;
  setAccessToken: (token: string) => void;
  clear: () => void;
  isAuthenticated: () => boolean;
  hasPermission: (code: string) => boolean;
}

export const useAdminAuthStore = create<AdminAuthState>((set, get) => ({
  accessToken: null,
  admin: null,

  setSession: (token, admin) => set({ accessToken: token, admin }),
  setAccessToken: (token) => set({ accessToken: token }),
  clear: () => set({ accessToken: null, admin: null }),

  isAuthenticated: () => Boolean(get().accessToken),
  hasPermission: (code) => {
    const admin = get().admin;
    if (!admin) return false;
    // 超级管理员拥有全部权限
    return admin.role === 'super_admin' || admin.permissions.includes(code);
  },
}));
