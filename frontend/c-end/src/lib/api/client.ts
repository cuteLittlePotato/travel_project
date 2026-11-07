/**
 * 服务端 fetch 封装（供 SSR 使用）。
 *
 * SSR 首屏不查询登录态（评审 §Q1）：不读取浏览器 Cookie，
 * 首屏统一渲染未登录视图，客户端 hydrate 后再补充登录态数据。
 */
import 'server-only';

import type { ApiResponse } from '@/types/api';

const BASE_URL = process.env.API_INTERNAL_BASE_URL ?? 'http://127.0.0.1:8000';

export class ApiError extends Error {
  constructor(
    readonly code: number,
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

interface ServerFetchOptions extends Omit<RequestInit, 'body'> {
  /** 单位秒，默认 10s；避免 SSR 被后端拖死 */
  revalidate?: number;
}

/**
 * 服务端 GET 请求。渲染期失败时抛出 ApiError，由页面降级展示。
 */
export async function serverGet<T>(
  path: string,
  { revalidate = 60, ...init }: ServerFetchOptions = {},
): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { Accept: 'application/json', ...init.headers },
    next: { revalidate },
  });

  const payload = (await response.json()) as ApiResponse<T>;

  if (!response.ok || payload.code !== 0) {
    throw new ApiError(payload.code, payload.message, response.status);
  }

  return payload.data as T;
}
