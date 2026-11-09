/**
 * 认证服务（API §3.1 ~ §3.7）。
 *
 * 统一封装所有认证相关的接口调用，页面组件不直接调 http。
 *
 * Token 策略（评审 §Q1）：
 *   - Access Token 由调用方存入内存（Zustand），本模块不碰 localStorage
 *   - Refresh Token 由后端写入 httpOnly Cookie，前端完全不可见
 */

import { http, parseApiError } from '@/lib/api/http';
import type { ApiResponse } from '@/types/api';

// ============================================================
// 类型
// ============================================================

export type VerifyScene = 'register' | 'login' | 'reset_password';
export type OAuthProvider = 'wechat' | 'alipay' | 'weibo';

export interface AuthUser {
  user_id: string;
  nickname?: string;
  avatar_url?: string | null;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export interface LoginResult extends AuthTokens {
  user_id: string;
}

export interface CodeLoginResult extends LoginResult {
  is_new_user: boolean;
}

export interface SendCodeResult {
  expires_in: number;
  /** 仅开发环境返回，生产为 undefined */
  debug_code?: string;
}

export interface SendCodePayload {
  target: string;
  scene: VerifyScene;
}

export interface RegisterPayload {
  target: string;
  verify_code: string;
  password: string;
  nickname?: string;
}

export interface LoginPayload {
  target: string;
  password: string;
}

export interface CodeLoginPayload {
  target: string;
  verify_code: string;
}

// ============================================================
// 内部：统一解包
// ============================================================

/** 抛出带业务码的错误，供调用方按 code 分支处理 */
export class AuthApiError extends Error {
  constructor(
    readonly code: number,
    message: string,
  ) {
    super(message);
    this.name = 'AuthApiError';
  }
}

async function unwrap<T>(request: Promise<{ data: ApiResponse<T> }>): Promise<T> {
  try {
    const { data } = await request;
    if (data.code !== 0 || data.data === null) {
      throw new AuthApiError(data.code, data.message);
    }
    return data.data;
  } catch (error) {
    if (error instanceof AuthApiError) throw error;
    const parsed = parseApiError(error);
    throw new AuthApiError(parsed.code, parsed.message);
  }
}

// ============================================================
// 接口
// ============================================================

/** 发送验证码（API §3.1） */
export function sendVerificationCode(payload: SendCodePayload): Promise<SendCodeResult> {
  return unwrap(
    http.post<ApiResponse<SendCodeResult>>('/api/v1/auth/verification-codes', payload),
  );
}

/** 注册（API §3.2） */
export function register(payload: RegisterPayload): Promise<LoginResult> {
  return unwrap(http.post<ApiResponse<LoginResult>>('/api/v1/auth/register', payload));
}

/** 密码登录（API §3.3） */
export function login(payload: LoginPayload): Promise<LoginResult> {
  return unwrap(http.post<ApiResponse<LoginResult>>('/api/v1/auth/login', payload));
}

/** 验证码登录，未注册则自动注册（API §3.4） */
export function loginByCode(payload: CodeLoginPayload): Promise<CodeLoginResult> {
  return unwrap(
    http.post<ApiResponse<CodeLoginResult>>('/api/v1/auth/login-by-code', payload),
  );
}

/** 第三方登录（API §3.5） */
export function oauthLogin(payload: {
  provider: OAuthProvider;
  code: string;
  state: string;
}): Promise<CodeLoginResult> {
  return unwrap(
    http.post<ApiResponse<CodeLoginResult>>('/api/v1/auth/oauth-login', payload),
  );
}

/** 刷新 Token（API §3.6）。Refresh Token 走 httpOnly Cookie，无需传参 */
export function refreshTokens(): Promise<AuthTokens> {
  return unwrap(http.post<ApiResponse<AuthTokens>>('/api/v1/auth/refresh', {}));
}

/** 登出，全端失效（API §3.7） */
export async function logout(): Promise<void> {
  await http.post('/api/v1/auth/logout');
}
