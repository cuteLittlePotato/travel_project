/**
 * 验证码按钮的组件测试（M01-T16 DoD）。
 *
 * DoD：「验证码按钮 60 秒倒计时可点击态切换」
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';

import { COUNTDOWN_SECONDS, VerificationCodeButton } from './VerificationCodeButton';

describe('VerificationCodeButton', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('初始状态可点击，文案为「获取验证码」', () => {
    render(<VerificationCodeButton onSend={vi.fn()} />);

    const button = screen.getByRole('button');
    expect(button).toHaveTextContent('获取验证码');
    expect(button).toBeEnabled();
  });

  it('点击后进入倒计时，按钮禁用', async () => {
    const onSend = vi.fn().mockResolvedValue(undefined);

    render(<VerificationCodeButton onSend={onSend} />);
    fireEvent.click(screen.getByRole('button'));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });


    expect(onSend).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button')).toBeDisabled();
    expect(screen.getByRole('button')).toHaveTextContent(`${COUNTDOWN_SECONDS}s`);
  });

  it('倒计时每秒递减', async () => {
    render(<VerificationCodeButton onSend={vi.fn().mockResolvedValue(undefined)} />);

    fireEvent.click(screen.getByRole('button'));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByRole('button')).toHaveTextContent(`${COUNTDOWN_SECONDS}s`);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByRole('button')).toHaveTextContent(`${COUNTDOWN_SECONDS - 1}s`);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByRole('button')).toHaveTextContent(`${COUNTDOWN_SECONDS - 2}s`);
  });

  it('倒计时结束后恢复可点击', async () => {
    render(<VerificationCodeButton onSend={vi.fn().mockResolvedValue(undefined)} />);

    fireEvent.click(screen.getByRole('button'));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      vi.advanceTimersByTime(COUNTDOWN_SECONDS * 1000);
    });

    const button = screen.getByRole('button');
    expect(button).toBeEnabled();
    expect(button).toHaveTextContent('获取验证码');
  });

  it('发送失败不进入倒计时，可立即重试', async () => {
    const onSend = vi.fn().mockRejectedValue(new Error('发送失败'));

    render(<VerificationCodeButton onSend={onSend} />);
    fireEvent.click(screen.getByRole('button'));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => {
      await Promise.resolve();
    });

    const button = screen.getByRole('button');
    expect(button).toBeEnabled();
    expect(button).toHaveTextContent('获取验证码');
  });

  it('倒计时期间重复点击不触发 onSend', async () => {
    const onSend = vi.fn().mockResolvedValue(undefined);

    render(<VerificationCodeButton onSend={onSend} />);
    fireEvent.click(screen.getByRole('button'));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => {
      await Promise.resolve();
    });

    // 按钮已 disabled，点击无效
    fireEvent.click(screen.getByRole('button'));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it('外部 disabled 时不响应点击', async () => {
    const onSend = vi.fn();

    render(<VerificationCodeButton onSend={onSend} disabled />);
    fireEvent.click(screen.getByRole('button'));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(onSend).not.toHaveBeenCalled();
  });

  it('卸载后定时器被清理（不会对已卸载组件 setState）', () => {
    const { unmount } = render(
      <VerificationCodeButton onSend={vi.fn().mockResolvedValue(undefined)} />,
    );

    unmount();

    // 卸载后推进时间不应抛错
    expect(() => {
      act(() => {
        vi.advanceTimersByTime(COUNTDOWN_SECONDS * 1000);
      });
    }).not.toThrow();
  });
});
