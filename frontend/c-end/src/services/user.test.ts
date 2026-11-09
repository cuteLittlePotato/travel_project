/**
 * C 端用户服务的测试。
 *
 * 重点覆盖 `unwrap` 对 **204 No Content** 的处理。
 *
 * 真实 bug：偏好设置保存时报错，且错误提示是**空的**（只有红叉没文字）。
 * 根因是 PUT/PATCH 返回 204 无响应体，axios 的 `response.data` 是空字符串，
 * `data.code` 得到 `undefined`，被 `!== 0` 误判为失败，
 * 抛出 `new UserApiError(undefined, undefined)`。
 */
import { AxiosHeaders, type AxiosResponse } from 'axios';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockGet = vi.fn();
const mockPut = vi.fn();

// mock http 模块本身，而不是 spy 方法——
// user.ts 在加载时就把 http 引用解析好了，spy 替换不到
vi.mock('@/lib/api/http', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/http')>(
    '@/lib/api/http',
  );
  return {
    ...actual,
    http: {
      get: (...args: unknown[]) => mockGet(...args),
      put: (...args: unknown[]) => mockPut(...args),
      patch: (...args: unknown[]) => mockPut(...args),
    },
  };
});

import { UserApiError } from './user';

function makeResponse(status: number, data: unknown): AxiosResponse<unknown> {
  return {
    status,
    statusText: '',
    data,
    headers: new AxiosHeaders(),
    config: { headers: new AxiosHeaders() },
  } as AxiosResponse<unknown>;
}

const EMPTY_PROFILE = {
  travel_types: [],
  travel_styles: [],
  budget_level: null,
  companion_type: null,
  preferred_seasons: [],
  departure_city: null,
};

describe('user service unwrap', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPut.mockReset();
  });

  it('正常响应返回 data', async () => {
    mockGet.mockResolvedValue(
      makeResponse(200, {
        code: 0,
        message: 'ok',
        data: { ...EMPTY_PROFILE, travel_types: ['历史人文'] },
      }),
    );

    const { getTravelProfile } = await import('./user');
    const result = await getTravelProfile();

    expect(result.travel_types).toEqual(['历史人文']);
  });

  it('**204 响应不抛错**', async () => {
    // 后端 204 无 body，axios 的 data 是空字符串
    mockPut.mockResolvedValue(makeResponse(204, ''));

    const { updateTravelProfile } = await import('./user');

    await expect(updateTravelProfile(EMPTY_PROFILE)).resolves.toBeUndefined();
  });

  it('**204 不会抛出 message 为 undefined 的错误**', async () => {
    // 修复前：会抛 new UserApiError(undefined, undefined)，
    // 前端 message.error(undefined) → 只有红叉没有文字的空提示
    mockPut.mockResolvedValue(makeResponse(204, ''));

    const { updateSettings } = await import('./user');

    let caught: unknown = null;
    try {
      await updateSettings({ allow_recommendation: true });
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeNull();
  });

  it('业务错误码抛 UserApiError 并带 message', async () => {
    mockPut.mockResolvedValue(
      makeResponse(400, { code: 10001, message: '参数校验失败', data: null }),
    );

    const { updateSettings } = await import('./user');

    await expect(updateSettings({ allow_recommendation: true })).rejects.toThrow(
      '参数校验失败',
    );
  });

  it('业务错误抛出的确实是 UserApiError', async () => {
    mockPut.mockResolvedValue(
      makeResponse(400, { code: 11005, message: '用户不存在', data: null }),
    );

    const { updateSettings } = await import('./user');

    try {
      await updateSettings({});
      expect.unreachable('应当抛错');
    } catch (error) {
      expect(error).toBeInstanceOf(UserApiError);
      expect((error as UserApiError).code).toBe(11005);
      expect((error as UserApiError).message).toBe('用户不存在');
    }
  });

  it('code=0 但 data 为 null 时返回 null', async () => {
    mockGet.mockResolvedValue(
      makeResponse(200, { code: 0, message: 'ok', data: null }),
    );

    const { getSettings } = await import('./user');

    await expect(getSettings()).resolves.toBeNull();
  });

  it('网络错误被转成 UserApiError', async () => {
    mockPut.mockRejectedValue(new Error('Network Error'));

    const { updateSettings } = await import('./user');

    try {
      await updateSettings({});
      expect.unreachable('应当抛错');
    } catch (error) {
      expect(error).toBeInstanceOf(UserApiError);
      // parseApiError 对非 axios 错误返回「未知错误」
      expect((error as UserApiError).message).toBeTruthy();
    }
  });
});
