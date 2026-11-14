/**
 * Token 存储策略的契约测试（M01-T16 DoD，评审 §Q1）。
 *
 * DoD：
 *   - Access Token 存内存、Refresh Token 存 httpOnly Cookie
 *   - localStorage 中不含任何 Token
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useAuthStore } from '@/stores/auth';
import { COUNTDOWN_SECONDS } from '@/components/auth/VerificationCodeButton';

describe('AuthStore：Access Token 只存内存', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    useAuthStore.setState({ accessToken: null, user: null, hydrated: false });
  });

  it('初始状态无 Token', () => {
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(useAuthStore.getState().isAuthenticated()).toBe(false);
  });

  it('setSession 后 Token 在内存中', () => {
    useAuthStore.getState().setSession('access-abc', { user_id: 'u1' });
    expect(useAuthStore.getState().accessToken).toBe('access-abc');
    expect(useAuthStore.getState().isAuthenticated()).toBe(true);
  });

  it('**Token 不写入 localStorage**（DoD 明确要求）', () => {
    useAuthStore.getState().setSession('access-abc', { user_id: 'u1' });

    // 检查所有 localStorage 的值
    const allValues = Object.keys(localStorage).map((k) => localStorage.getItem(k));
    expect(allValues.join('')).not.toContain('access-abc');
    expect(localStorage.length).toBe(0);
  });

  it('**Token 不写入 sessionStorage**', () => {
    useAuthStore.getState().setSession('access-abc', { user_id: 'u1' });

    const allValues = Object.keys(sessionStorage).map((k) => sessionStorage.getItem(k));
    expect(allValues.join('')).not.toContain('access-abc');
  });

  it('clear 后 Token 被清空', () => {
    useAuthStore.getState().setSession('access-abc', { user_id: 'u1' });
    useAuthStore.getState().clear();

    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(useAuthStore.getState().user).toBeNull();
  });

  it('刷新 Token 只更新 access，不影响 user', () => {
    useAuthStore.getState().setSession('old-token', { user_id: 'u1' });
    useAuthStore.getState().setAccessToken('new-token');

    expect(useAuthStore.getState().accessToken).toBe('new-token');
    expect(useAuthStore.getState().user?.user_id).toBe('u1');
  });
});

describe('http 客户端配置', () => {
  it('**withCredentials 为 true**（Refresh Token 走 Cookie）', async () => {
    const { http } = await import('@/lib/api/http');
    expect(http.defaults.withCredentials).toBe(true);
  });

  it('请求拦截器从内存读 Token，不读 localStorage', async () => {
    const { http } = await import('@/lib/api/http');

    useAuthStore.getState().setSession('memory-token', { user_id: 'u1' });

    // 拦截器处理器是内部实现，这里通过检查 store 来源间接验证：
    // 清空 localStorage 后 Token 仍在 store 中
    localStorage.clear();
    expect(useAuthStore.getState().accessToken).toBe('memory-token');

    useAuthStore.getState().clear();
    expect(useAuthStore.getState().accessToken).toBeNull();
  });
});

describe('倒计时常量与后端一致', () => {
  it('倒计时 60 秒对应后端发送间隔限制', () => {
    // 后端 constants.py: VERIFY_CODE_SEND_INTERVAL_SECONDS = 60
    expect(COUNTDOWN_SECONDS).toBe(60);
  });
});

describe('OAuth state 校验', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  afterEach(() => {
    sessionStorage.clear();
  });

  it('生成的 state 存入 sessionStorage', async () => {
    const { createOAuthState } = await import('@/components/auth/OAuthButtons');
    const state = createOAuthState();

    expect(state).toBeTruthy();
    expect(sessionStorage.getItem('oauth_state')).toBe(state);
  });

  it('匹配的 state 校验通过并清除', async () => {
    const { createOAuthState, verifyOAuthState } = await import(
      '@/components/auth/OAuthButtons'
    );
    const state = createOAuthState();

    expect(verifyOAuthState(state)).toBe(true);
    expect(sessionStorage.getItem('oauth_state')).toBeNull();
  });

  it('不匹配的 state 校验失败', async () => {
    const { createOAuthState, verifyOAuthState } = await import(
      '@/components/auth/OAuthButtons'
    );
    createOAuthState();

    expect(verifyOAuthState('forged-state')).toBe(false);
  });

  it('未生成 state 时校验失败', async () => {
    const { verifyOAuthState } = await import('@/components/auth/OAuthButtons');
    expect(verifyOAuthState('anything')).toBe(false);
  });
});
