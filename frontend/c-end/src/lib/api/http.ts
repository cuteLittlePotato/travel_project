/**
 * 客户端 Axios 实例。
 *
 * Token 策略（评审 §Q1）：Access Token 存内存（Zustand store），
 * Refresh Token 存 httpOnly Cookie，JS 不可读。
 * 401 时自动刷新一次并重放原请求，并发 401 只触发一次刷新。
 */
import axios, { AxiosError, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios';

import { useAuthStore } from '@/stores/auth';
import type { ApiResponse } from '@/types/api';

export const http = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_BASE_URL ?? '',
  timeout: 30_000,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});

/** 刷新接口本身失败时不再递归刷新 */
const REFRESH_PATH = '/api/v1/auth/refresh';
let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  try {
    const { data } = await axios.post<ApiResponse<{ access_token: string }>>(
      REFRESH_PATH,
      {},
      { withCredentials: true, baseURL: http.defaults.baseURL },
    );
    return data.code === 0 ? (data.data?.access_token ?? null) : null;
  } catch {
    return null;
  }
}

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = useAuthStore.getState().accessToken;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiResponse<unknown>>) => {
    const config = error.config as (AxiosRequestConfig & { _retried?: boolean }) | undefined;
    const status = error.response?.status;

    if (status === 401 && config && !config._retried && config.url !== REFRESH_PATH) {
      config._retried = true;

      // 并发请求同时 401 时共享同一次刷新
      refreshPromise ??= refreshAccessToken().finally(() => {
        refreshPromise = null;
      });
      const newToken = await refreshPromise;

      if (newToken) {
        useAuthStore.getState().setAccessToken(newToken);
        config.headers = { ...config.headers, Authorization: `Bearer ${newToken}` };
        return http.request(config);
      }

      useAuthStore.getState().clear();
      if (typeof window !== 'undefined') {
        window.location.href = '/login';
      }
    }

    return Promise.reject(error);
  },
);

/** 从 Axios 错误中提取业务码与提示文案 */
export function parseApiError(error: unknown): { code: number; message: string } {
  if (axios.isAxiosError<ApiResponse<unknown>>(error)) {
    const payload = error.response?.data;
    if (payload) {
      return { code: payload.code, message: payload.message };
    }
    return { code: -1, message: error.message || '网络异常，请稍后重试' };
  }
  return { code: -1, message: '未知错误' };
}
