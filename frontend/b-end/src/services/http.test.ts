/**
 * B 端 HTTP 封装的测试。
 *
 * 重点覆盖 204 No Content 的处理——这是个真实踩过的坑：
 * PUT/DELETE 返回 204 时没有响应体，`data` 是空字符串，
 * 直接读 `data.code` 会得到 undefined 并被误判为业务失败，
 * 页面弹出无意义的「保存失败」。
 *
 * **测试的是真实的 `request` 函数**：用 `vi.spyOn` 替换 http 实例的
 * request 方法，而不是 mock 整个模块。复制一份解包逻辑来测没有任何
 * 防回归价值——被改错的实现照样能通过复制出来的测试。
 */
import { AxiosError, AxiosHeaders, type AxiosResponse } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { http, request } from './http';

function makeResponse(status: number, data: unknown): AxiosResponse<unknown> {
  return {
    status,
    statusText: '',
    data,
    headers: new AxiosHeaders(),
    config: { headers: new AxiosHeaders() },
  } as AxiosResponse<unknown>;
}

describe('request 解包', () => {
  let requestSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    requestSpy = vi.spyOn(http, 'request');
  });

  afterEach(() => {
    requestSpy.mockRestore();
  });

  it('正常响应返回 data 部分', async () => {
    requestSpy.mockResolvedValue(
      makeResponse(200, { code: 0, message: 'ok', data: { id: '1', name: '测试' } }),
    );

    const result = await request<{ id: string; name: string }>({ url: '/x' });

    expect(result).toEqual({ id: '1', name: '测试' });
  });

  it('**204 响应返回 null，不抛错**', async () => {
    // 后端 204 无 body，axios 的 response.data 是空字符串
    requestSpy.mockResolvedValue(makeResponse(204, ''));

    await expect(
      request<null>({ url: '/system/roles/1/permissions', method: 'PUT' }),
    ).resolves.toBeNull();
  });

  it('**204 不会被误判为业务失败**', async () => {
    requestSpy.mockResolvedValue(makeResponse(204, ''));

    // 修复前：data 是空串 → data.code 为 undefined
    // → 抛出 new Error(undefined)，message 为空，页面提示「保存失败」
    await expect(request<null>({ url: '/x', method: 'DELETE' })).resolves.toBeNull();
  });

  it('业务错误码抛错并带 message', async () => {
    requestSpy.mockResolvedValue(
      makeResponse(409, { code: 25005, message: '该角色已分配给管理员', data: null }),
    );

    await expect(request({ url: '/x' })).rejects.toThrow('该角色已分配给管理员');
  });

  it('code=0 但 data 为 null 时返回 null', async () => {
    requestSpy.mockResolvedValue(
      makeResponse(200, { code: 0, message: 'ok', data: null }),
    );

    await expect(request<null>({ url: '/x' })).resolves.toBeNull();
  });

  it('空响应体（非 204）也返回 null 而不是抛错', async () => {
    requestSpy.mockResolvedValue(makeResponse(200, ''));

    await expect(request<null>({ url: '/x' })).resolves.toBeNull();
  });

  it('网络错误原样抛出，便于上层展示', async () => {
    requestSpy.mockRejectedValue(new AxiosError('Network Error'));

    await expect(request({ url: '/x' })).rejects.toThrow('Network Error');
  });
});
