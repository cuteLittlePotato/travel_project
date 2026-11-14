/**
 * B 端 Axios 实例与拦截器。
 *
 * Token 策略与 C 端一致（评审 §Q1）：Access 存内存，Refresh 存 httpOnly Cookie。
 */
import axios, { AxiosError, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios';
import { message } from 'antd';

import { useAdminAuthStore } from '@/stores/auth';
import type { ApiResponse } from '@/types/api';

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api/v1/admin',
  timeout: 30_000,
  withCredentials: true,
});

const REFRESH_PATH = '/auth/refresh';
let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  try {
    const { data } = await axios.post<ApiResponse<{ access_token: string }>>(
      `${http.defaults.baseURL}${REFRESH_PATH}`,
      {},
      { withCredentials: true },
    );
    return data.code === 0 ? (data.data?.access_token ?? null) : null;
  } catch {
    return null;
  }
}

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = useAdminAuthStore.getState().accessToken;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiResponse<unknown>>) => {
    const config = error.config as (AxiosRequestConfig & { _retried?: boolean }) | undefined;

    if (error.response?.status === 401 && config && !config._retried && config.url !== REFRESH_PATH) {
      config._retried = true;
      refreshPromise ??= refreshAccessToken().finally(() => {
        refreshPromise = null;
      });
      const newToken = await refreshPromise;

      if (newToken) {
        useAdminAuthStore.getState().setAccessToken(newToken);
        config.headers = { ...config.headers, Authorization: `Bearer ${newToken}` };
        return http.request(config);
      }

      useAdminAuthStore.getState().clear();
      window.location.href = `${import.meta.env.BASE_URL}login`;
      return Promise.reject(error);
    }

    const payload = error.response?.data;
    if (payload?.message) {
      message.error(payload.message);
    } else if (error.response?.status === 429) {
      message.error('请求过于频繁，请稍后再试');
    } else if (!error.response) {
      message.error('网络异常，请检查连接');
    }

    return Promise.reject(error);
  },
);

/** 解包统一响应，直接返回 data 部分 */
export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const response = await http.request<ApiResponse<T>>(config);

  // 204 No Content 没有响应体（PUT/DELETE 的常规返回），
  // 此时 data 是空字符串。直接读 data.code 会拿到 undefined，
  // 被误判成「业务失败」而抛出无意义的错误。
  if (response.status === 204 || !response.data) {
    return null as T;
  }

  const { data } = response;
  if (data.code !== 0) {
    throw new Error(data.message);
  }
  return data.data as T;
}
