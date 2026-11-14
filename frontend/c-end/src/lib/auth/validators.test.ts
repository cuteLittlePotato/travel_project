/**
 * 认证表单校验的单测（M01-T16 DoD）。
 *
 * DoD：「表单校验失败时不发起请求」——本测试保证校验函数能正确拦截。
 * 规则必须与后端 `app/modules/account/constants.py` 一致。
 */
import { describe, expect, it } from 'vitest';

import {
  NICKNAME_MAX_LENGTH,
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  VERIFY_CODE_LENGTH,
  getNicknameError,
  getPasswordError,
  getTargetError,
  getVerifyCodeError,
  isValidEmail,
  isValidPassword,
  isValidPhone,
  isValidTarget,
  isValidVerifyCode,
} from './validators';

describe('isValidPhone', () => {
  it.each(['13800138000', '19912345678', '15012345678'])('接受 %s', (phone) => {
    expect(isValidPhone(phone)).toBe(true);
  });

  it.each(['', '12345', '1234567890', '123456789012', '23800138000', 'abc'])(
    '拒绝 %s',
    (phone) => {
      expect(isValidPhone(phone)).toBe(false);
    },
  );

  it('忽略首尾空格', () => {
    expect(isValidPhone('  13800138000  ')).toBe(true);
  });
});

describe('isValidEmail', () => {
  it.each(['a@b.com', 'user.name@example.co.uk', 'x+tag@mail.cn'])('接受 %s', (email) => {
    expect(isValidEmail(email)).toBe(true);
  });

  it.each(['', 'a@b', '@b.com', 'a b@c.com', 'abc'])('拒绝 %s', (email) => {
    expect(isValidEmail(email)).toBe(false);
  });
});

describe('isValidTarget', () => {
  it('接受手机号或邮箱', () => {
    expect(isValidTarget('13800138000')).toBe(true);
    expect(isValidTarget('a@b.com')).toBe(true);
  });

  it('拒绝两者都不是的值', () => {
    expect(isValidTarget('abc')).toBe(false);
  });
});

describe('getTargetError', () => {
  it('空值提示必填', () => {
    expect(getTargetError('')).toBe('请输入手机号或邮箱');
  });

  it('纯数字但格式错误 → 提示手机号', () => {
    expect(getTargetError('12345')).toBe('手机号格式不正确');
  });

  it('非数字且非邮箱 → 提示邮箱', () => {
    expect(getTargetError('abcdef')).toBe('邮箱格式不正确');
  });

  it('合法值返回 null', () => {
    expect(getTargetError('13800138000')).toBeNull();
    expect(getTargetError('a@b.com')).toBeNull();
  });
});

describe('isValidPassword / getPasswordError', () => {
  it('合法密码', () => {
    expect(isValidPassword('Passw0rd')).toBe(true);
    expect(getPasswordError('Passw0rd')).toBeNull();
  });

  it(`少于 ${PASSWORD_MIN_LENGTH} 位被拒绝`, () => {
    const short = 'Ab1';
    expect(isValidPassword(short)).toBe(false);
    expect(getPasswordError(short)).toContain('至少');
  });

  it(`超过 ${PASSWORD_MAX_LENGTH} 位被拒绝`, () => {
    const long = `A1${'a'.repeat(PASSWORD_MAX_LENGTH)}`;
    expect(isValidPassword(long)).toBe(false);
    expect(getPasswordError(long)).toContain('最多');
  });

  it('缺少字母被拒绝', () => {
    expect(isValidPassword('12345678')).toBe(false);
    expect(getPasswordError('12345678')).toBe('密码需包含字母');
  });

  it('缺少数字被拒绝', () => {
    expect(isValidPassword('abcdefgh')).toBe(false);
    expect(getPasswordError('abcdefgh')).toBe('密码需包含数字');
  });

  it('空值提示必填', () => {
    expect(getPasswordError('')).toBe('请输入密码');
  });
});

describe('isValidVerifyCode / getVerifyCodeError', () => {
  it(`${VERIFY_CODE_LENGTH} 位数字合法`, () => {
    expect(isValidVerifyCode('123456')).toBe(true);
    expect(getVerifyCodeError('123456')).toBeNull();
  });

  it('长度不对被拒绝', () => {
    expect(isValidVerifyCode('12345')).toBe(false);
    expect(isValidVerifyCode('1234567')).toBe(false);
  });

  it('含非数字被拒绝', () => {
    expect(isValidVerifyCode('12345a')).toBe(false);
    expect(getVerifyCodeError('12345a')).toBe('验证码只能包含数字');
  });

  it('空值提示必填', () => {
    expect(getVerifyCodeError('')).toBe('请输入验证码');
  });
});

describe('getNicknameError', () => {
  it('空值合法（可选字段）', () => {
    expect(getNicknameError(undefined)).toBeNull();
    expect(getNicknameError('')).toBeNull();
  });

  it('纯空白被拒绝', () => {
    expect(getNicknameError('   ')).toBe('昵称不能为空白');
  });

  it(`超过 ${NICKNAME_MAX_LENGTH} 字符被拒绝`, () => {
    expect(getNicknameError('x'.repeat(NICKNAME_MAX_LENGTH + 1))).toContain('最多');
  });

  it('合法昵称通过', () => {
    expect(getNicknameError('旅行者')).toBeNull();
  });
});
