/**
 * B 端认证服务（API §14.14 ~ §14.16）。
 */
import { request } from '@/services/http';
import type { AdminUser } from '@/stores/auth';

export interface LoginPayload {
  username: string;
  password: string;
}

export interface LoginResult {
  access_token: string;
  refresh_token: string;
  token_type: 'bearer';
  expires_in: number;
  user_type: 'admin';
  admin: AdminUser;
}

export interface ChangePasswordPayload {
  old_password: string;
  new_password: string;
}

export function login(payload: LoginPayload): Promise<LoginResult> {
  return request({ url: '/auth/login', method: 'POST', data: payload });
}

export async function logout(): Promise<void> {
  await request<null>({ url: '/auth/logout', method: 'POST' });
}

/**
 * 刷新 Token。
 *
 * Refresh Token 在 httpOnly Cookie 里（评审 §Q1），JS 读不到，
 * 因此请求体为空——浏览器会自动带上 Cookie。
 * `withCredentials` 在 http 实例上已开启。
 */
export function refreshToken(): Promise<LoginResult> {
  return request({ url: '/auth/refresh', method: 'POST' });
}

export async function changeOwnPassword(
  payload: ChangePasswordPayload,
): Promise<void> {
  await request<null>({ url: '/me/password', method: 'PUT', data: payload });
}
