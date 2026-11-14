/**
 * 认证状态（Zustand）。
 *
 * Access Token 只存内存，不落 localStorage / sessionStorage（评审 §Q1）。
 * Refresh Token 由后端写入 httpOnly Cookie，前端不可见。
 */
import { create } from 'zustand';

export interface AuthUser {
  user_id: string;
  nickname?: string | null;
  avatar_url?: string | null;
}

interface AuthState {
  accessToken: string | null;
  user: AuthUser | null;
  /** 是否已完成首次登录态探测（用于避免闪烁） */
  hydrated: boolean;
  setSession: (token: string, user: AuthUser) => void;
  setAccessToken: (token: string) => void;
  setUser: (user: AuthUser) => void;
  setHydrated: (hydrated: boolean) => void;
  clear: () => void;
  isAuthenticated: () => boolean;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,
  user: null,
  hydrated: false,

  setSession: (token, user) => set({ accessToken: token, user, hydrated: true }),
  setAccessToken: (token) => set({ accessToken: token }),
  setUser: (user) => set({ user }),
  setHydrated: (hydrated) => set({ hydrated }),
  clear: () => set({ accessToken: null, user: null, hydrated: true }),

  isAuthenticated: () => Boolean(get().accessToken),
}));
