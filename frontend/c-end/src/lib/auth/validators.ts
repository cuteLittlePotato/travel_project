/**
 * 认证表单校验规则（与后端一致）。
 *
 * 抽成纯函数而非内联在组件里，原因：
 *   1. 可单测（DoD 要求「表单校验失败时不发起请求」）
 *   2. 前后端规则一致，便于比对
 *
 * 后端规则来源：`app/modules/account/constants.py` 的
 * `PHONE_PATTERN` / `EMAIL_PATTERN` / `PASSWORD_PATTERN`。
 */

/** 手机号：中国大陆 11 位 */
const PHONE_REGEX = /^1[3-9]\d{9}$/;
/** 邮箱：宽松校验，与后端一致 */
const EMAIL_REGEX = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;
/** 密码：8-32 位，必须同时含字母与数字 */
const PASSWORD_REGEX = /^(?=.*[A-Za-z])(?=.*\d).{8,32}$/;

export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_LENGTH = 32;
export const VERIFY_CODE_LENGTH = 6;
export const NICKNAME_MAX_LENGTH = 50;

export function isValidPhone(value: string): boolean {
  return PHONE_REGEX.test(value.trim());
}

export function isValidEmail(value: string): boolean {
  return EMAIL_REGEX.test(value.trim());
}

/** target 可以是手机号或邮箱 */
export function isValidTarget(value: string): boolean {
  const trimmed = value.trim();
  return isValidPhone(trimmed) || isValidEmail(trimmed);
}

export function isValidPassword(value: string): boolean {
  return PASSWORD_REGEX.test(value);
}

export function isValidVerifyCode(value: string): boolean {
  return new RegExp(`^\\d{${VERIFY_CODE_LENGTH}}$`).test(value);
}

/**
 * 返回密码强度问题的描述，无问题返回 null。
 *
 * 分开返回具体原因，前端可展示「缺少数字」而非笼统的「格式错误」。
 */
export function getPasswordError(value: string): string | null {
  if (!value) return '请输入密码';
  if (value.length < PASSWORD_MIN_LENGTH) return `密码至少 ${PASSWORD_MIN_LENGTH} 位`;
  if (value.length > PASSWORD_MAX_LENGTH) return `密码最多 ${PASSWORD_MAX_LENGTH} 位`;
  if (!/[A-Za-z]/.test(value)) return '密码需包含字母';
  if (!/\d/.test(value)) return '密码需包含数字';
  return null;
}

/** target 的具体错误描述 */
export function getTargetError(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return '请输入手机号或邮箱';
  if (isValidPhone(trimmed)) return null;
  if (isValidEmail(trimmed)) return null;
  // 全是数字但长度不对 → 更可能是手机号输错
  if (/^\d+$/.test(trimmed)) return '手机号格式不正确';
  return '邮箱格式不正确';
}

/** 验证码的具体错误描述 */
export function getVerifyCodeError(value: string): string | null {
  if (!value) return '请输入验证码';
  if (!/^\d+$/.test(value)) return '验证码只能包含数字';
  if (value.length !== VERIFY_CODE_LENGTH) return `验证码为 ${VERIFY_CODE_LENGTH} 位`;
  return null;
}

/** 昵称的具体错误描述（可选字段，空值合法） */
export function getNicknameError(value: string | undefined): string | null {
  if (!value) return null;
  if (value.trim().length === 0) return '昵称不能为空白';
  if (value.length > NICKNAME_MAX_LENGTH) return `昵称最多 ${NICKNAME_MAX_LENGTH} 字符`;
  return null;
}
