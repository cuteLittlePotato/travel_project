/**
 * 服务端 fetch 封装（供 SSR 使用）。
 *
 * SSR 首屏不查询登录态（评审 §Q1）：不读取浏览器 Cookie，
 * 首屏统一渲染未登录视图，客户端 hydrate 后再补充登录态数据。
 *
 * 降级策略（M0-T08 边界要求）：后端不可达时 SSR 不应整页 500，
 * 而是由调用方拿到 ``null`` 并渲染降级 UI。用 ``serverGetSafe``。
 */
import 'server-only';

import { env } from '@/lib/utils/env';
import type { ApiResponse } from '@/types/api';

const BASE_URL = env.internalBaseUrl;

/** 后端请求默认超时，避免后端挂起时 SSR 无限等待 */
const DEFAULT_TIMEOUT_MS = 8_000;

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
  /** ISR 缓存时间（秒），默认 60s */
  revalidate?: number;
  /** 单次请求超时（毫秒），默认 8s */
  timeoutMs?: number;
}

/**
 * 服务端 GET 请求。失败时抛 ``ApiError``，适合「必须有数据才能渲染」的页面
 * （交由 error.tsx 统一兜底）。
 */
export async function serverGet<T>(
  path: string,
  { revalidate = 60, timeoutMs = DEFAULT_TIMEOUT_MS, ...init }: ServerFetchOptions = {},
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { Accept: 'application/json', ...init.headers },
      next: { revalidate },
    });

    const payload = (await response.json()) as ApiResponse<T>;

    if (!response.ok || payload.code !== 0) {
      throw new ApiError(payload.code, payload.message, response.status);
    }

    return payload.data as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    // 网络错误、超时、非法 JSON 统一包装，避免把底层细节抛给页面
    const reason = error instanceof Error ? error.message : '未知错误';
    throw new ApiError(-1, `后端服务暂不可用：${reason}`, 503);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 降级版 GET：失败返回 ``{ data: null, error }`` 而不抛出。
 *
 * 用于「后端不可达时仍应能展示页面骨架」的场景，例如首页推荐位、
 * 景点列表：拿不到数据就展示空态，而不是整页 500。
 */
export async function serverGetSafe<T>(
  path: string,
  options: ServerFetchOptions = {},
): Promise<{ data: T | null; error: ApiError | null }> {
  try {
    return { data: await serverGet<T>(path, options), error: null };
  } catch (error) {
    return {
      data: null,
      error:
        error instanceof ApiError
          ? error
          : new ApiError(-1, '后端服务暂不可用', 503),
    };
  }
}
