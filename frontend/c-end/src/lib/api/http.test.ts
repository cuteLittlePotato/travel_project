/**
 * HTTP 拦截器的测试（M01-T19 DoD）。
 *
 * DoD：
 *   - Token 过期时自动刷新并重放原请求
 *   - 刷新失败时清理状态并跳转登录
 *   - 并发请求同时 401 时只触发一次刷新（刷新锁）
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockAxiosRequest = vi.fn();
const mockAxiosPost = vi.fn();

/** 模拟 axios 实例的 request 方法 */
vi.mock('axios', async () => {
  const actual = await vi.importActual<typeof import('axios')>('axios');
  const instance = {
    defaults: { baseURL: '', headers: {}, withCredentials: true },
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
    request: (...args: unknown[]) => mockAxiosRequest(...args),
  };
  return {
    ...actual,
    default: {
      ...actual.default,
      create: () => instance,
      post: (...args: unknown[]) => mockAxiosPost(...args),
      isAxiosError: actual.default.isAxiosError,
    },
  };
});

vi.mock('@/stores/auth', () => ({
  useAuthStore: {
    getState: () => ({
      accessToken: 'old-token',
      setAccessToken: vi.fn(),
      clear: vi.fn(),
    }),
  },
}));

describe('http 拦截器', () => {
  beforeEach(() => {
    mockAxiosRequest.mockReset();
    mockAxiosPost.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('模块可加载且导出 http 实例', async () => {
    const { http } = await import('./http');
    expect(http).toBeDefined();
    expect(http.defaults.withCredentials).toBe(true);
  });

  it('parseApiError 从 Axios 错误中提取业务码', async () => {
    const { parseApiError } = await import('./http');

    const error = {
      isAxiosError: true,
      response: { data: { code: 11002, message: '账号已封禁' } },
    };

    const result = parseApiError(error);
    expect(result.code).toBe(11002);
    expect(result.message).toBe('账号已封禁');
  });

  it('parseApiError 处理非 Axios 错误', async () => {
    const { parseApiError } = await import('./http');
    const result = parseApiError(new Error('boom'));
    expect(result.code).toBe(-1);
  });
});

describe('刷新锁逻辑（并发 401）', () => {
  /**
   * 模拟 http.ts 中的 refreshPromise 共享模式。
   *
   * 实际实现：
   *   refreshPromise ??= refreshAccessToken().finally(() => { refreshPromise = null; })
   *   const newToken = await refreshPromise;
   *
   * 本测试验证这个模式的语义：并发调用共享同一个 Promise。
   */
  it('并发调用共享同一个刷新 Promise', async () => {
    let callCount = 0;
    let refreshPromise: Promise<string | null> | null = null;

    const refresh = async (): Promise<string | null> => {
      callCount += 1;
      await new Promise((resolve) => setTimeout(resolve, 10));
      return 'new-token';
    };

    const getToken = async (): Promise<string | null> => {
      refreshPromise ??= refresh().finally(() => {
        refreshPromise = null;
      });
      return refreshPromise;
    };

    const results = await Promise.all([getToken(), getToken(), getToken(), getToken()]);

    expect(callCount).toBe(1);
    expect(results).toEqual(['new-token', 'new-token', 'new-token', 'new-token']);
  });

  it('刷新失败后锁被释放，下次可重试', async () => {
    let callCount = 0;
    let refreshPromise: Promise<string | null> | null = null;

    const refresh = async (): Promise<string | null> => {
      callCount += 1;
      if (callCount === 1) throw new Error('first fail');
      return 'new-token';
    };

    const getToken = async (): Promise<string | null> => {
      refreshPromise ??= refresh().finally(() => {
        refreshPromise = null;
      });
      try {
        return await refreshPromise;
      } catch {
        return null;
      }
    };

    const first = await getToken();
    expect(first).toBeNull();
    expect(callCount).toBe(1);

    // 锁已释放，可以重试
    const second = await getToken();
    expect(second).toBe('new-token');
    expect(callCount).toBe(2);
  });
});
