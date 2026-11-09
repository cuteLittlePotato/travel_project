'use client';

/**
 * 验证码发送按钮（DoD：60 秒倒计时可点击态切换）。
 *
 * 三种状态：
 *   1. 空闲：可点击，文案「获取验证码」
 *   2. 发送中：禁用，文案「发送中…」
 *   3. 倒计时：禁用，文案「60s 后重发」
 *
 * 倒计时在组件卸载时必须清理，否则切页面后 setState 会警告。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, type ButtonProps } from 'antd';

/** 倒计时秒数。与后端 60 秒间隔限制对应 */
export const COUNTDOWN_SECONDS = 60;

export interface VerificationCodeButtonProps extends Omit<ButtonProps, 'onClick'> {
  /** 点击时执行发送逻辑。抛错则不进入倒计时 */
  onSend: () => Promise<void> | void;
  /** 关闭倒计时（调试用） */
  disabled?: boolean;
}

export function VerificationCodeButton({
  onSend,
  disabled = false,
  ...rest
}: VerificationCodeButtonProps) {
  const [countdown, setCountdown] = useState(0);
  const [sending, setSending] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 组件卸载时清理定时器，避免对已卸载组件 setState
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const startCountdown = useCallback(() => {
    setCountdown(COUNTDOWN_SECONDS);

    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          if (timerRef.current) clearInterval(timerRef.current);
          timerRef.current = null;
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, []);

  const handleClick = async () => {
    if (countdown > 0 || sending || disabled) return;

    setSending(true);
    try {
      await onSend();
      // 只有发送成功才进入倒计时；失败时允许立即重试
      startCountdown();
    } catch {
      // 错误提示由调用方负责，这里只保证不进入倒计时
    } finally {
      setSending(false);
    }
  };

  const isCountingDown = countdown > 0;
  const isDisabled = disabled || sending || isCountingDown;

  let label = '获取验证码';
  if (sending) label = '发送中…';
  else if (isCountingDown) label = `${countdown}s 后重发`;

  return (
    <Button onClick={handleClick} disabled={isDisabled} {...rest}>
      {label}
    </Button>
  );
}
