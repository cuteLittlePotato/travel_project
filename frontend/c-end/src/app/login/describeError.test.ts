/**
 * 登录页错误文案的测试。
 *
 * 背景：验证码注册的账号没有密码，用户回到登录页用「密码登录」
 * 无论输什么都登不上，而原来只提示「密码错误」——他不知道
 * 自己从未设置过密码。后端现在用 11013 区分，前端据此给指引。
 */
import { describe, expect, it } from 'vitest';

import { describeError } from './describe-error';
import { AuthApiError } from '@/services/auth';

function makeError(code: number, message = ''): AuthApiError {
  return new AuthApiError(code, message);
}

describe('describeError', () => {
  it('11013 提示用验证码登录', () => {
    const text = describeError(makeError(11013, '该账号尚未设置密码'));

    expect(text).toContain('验证码登录');
    expect(text).toContain('尚未设置密码');
  });

  it('11006 提示账号或密码错误', () => {
    expect(describeError(makeError(11006, '账号或密码错误'))).toBe(
      '账号或密码错误',
    );
  });

  it('11005 与 11006 文案一致（防账号枚举）', () => {
    expect(describeError(makeError(11005))).toBe(
      describeError(makeError(11006)),
    );
  });

  it('11002 提示账号被封禁', () => {
    expect(describeError(makeError(11002))).toContain('封禁');
  });

  it('11007 提示账号已注销', () => {
    expect(describeError(makeError(11007))).toContain('注销');
  });

  it('11008 提示错误次数过多', () => {
    expect(describeError(makeError(11008))).toContain('次数过多');
  });

  it('11004 提示验证码错误', () => {
    expect(describeError(makeError(11004))).toContain('验证码');
  });

  it('未知错误码回退到后端 message', () => {
    expect(describeError(makeError(99999, '服务器开小差了'))).toBe(
      '服务器开小差了',
    );
  });

  it('未知错误码且无 message 时给通用文案', () => {
    expect(describeError(makeError(99999, ''))).toBe('登录失败，请稍后重试');
  });

  it('**每个已知错误码都有专属文案，不会落到通用兜底**', () => {
    // 防止新增错误码后忘记在前端补文案
    const knownCodes = [11002, 11004, 11005, 11006, 11007, 11008, 11013];
    for (const code of knownCodes) {
      const text = describeError(makeError(code, ''));
      expect(text).not.toBe('登录失败，请稍后重试');
    }
  });
});
