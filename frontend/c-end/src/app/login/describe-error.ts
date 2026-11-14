/**
 * 登录页的错误文案映射。
 *
 * 独立成文件而非放在 ``page.tsx`` 里：Next.js 的页面文件只允许导出
 * 特定成员（default / metadata / config 等），导出其他函数会触发
 * 类型检查错误。
 */

import type { AuthApiError } from '@/services/auth';

export function describeError(error: AuthApiError): string {
  switch (error.code) {
    case 11002:
      return '该账号已被封禁，请联系客服';
    case 11007:
      return '该账号已注销';
    case 11008:
      return '密码错误次数过多，请稍后再试';
    case 11004:
      return '验证码错误或已过期，请重新获取';
    case 10003:
      return '操作过于频繁，请稍后再试';
    case 11005:
    case 11006:
      // 后端为避免账号枚举，两者用同一文案
      return '账号或密码错误';
    case 11013:
      return '该账号尚未设置密码，请使用验证码登录';
    default:
      return error.message || '登录失败，请稍后重试';
  }
}
