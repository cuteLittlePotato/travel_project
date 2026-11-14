/**
 * 注册页「获取验证码」的边界测试。
 *
 * 与登录页同一问题：浏览器自动填充只改 DOM，不触发 React onChange，
 * antd Form store 里是空的 → 用户看到框里有邮箱，点了却提示「请填写」。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';

import RegisterPage from './page';

const mockSendCode = vi.fn();

vi.mock('@/services/auth', async () => {
  const actual = await vi.importActual<typeof import('@/services/auth')>(
    '@/services/auth',
  );
  return {
    ...actual,
    sendVerificationCode: (...args: unknown[]) => mockSendCode(...args),
    register: vi.fn(),
  };
});

function renderPage() {
  return render(
    <ConfigProvider locale={zhCN}>
      <AntdApp>
        <RegisterPage />
      </AntdApp>
    </ConfigProvider>,
  );
}

/** 模拟浏览器自动填充：直接设置 DOM value，不触发 React onChange */
function autofill(input: HTMLInputElement, value: string) {
  const nativeSetter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    'value',
  )?.set;
  nativeSetter?.call(input, value);
}

describe('注册页获取验证码', () => {
  beforeEach(() => {
    mockSendCode.mockReset();
    mockSendCode.mockResolvedValue({ expires_in: 300, debug_code: '123456' });
  });

  it('手动输入时正常发送', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(
      screen.getByPlaceholderText('请输入手机号或邮箱'),
      'newuser@example.com',
    );
    await user.click(screen.getByRole('button', { name: /获取验证码/ }));

    await waitFor(() => {
      expect(mockSendCode).toHaveBeenCalledWith({
        target: 'newuser@example.com',
        scene: 'register',
      });
    });
  });

  it('**自动填充只改 DOM 时也能发送**', async () => {
    const user = userEvent.setup();
    renderPage();

    const input = screen.getByPlaceholderText(
      '请输入手机号或邮箱',
    ) as HTMLInputElement;
    autofill(input, 'autofill@example.com');

    await user.click(screen.getByRole('button', { name: /获取验证码/ }));

    await waitFor(() => {
      expect(mockSendCode).toHaveBeenCalledWith({
        target: 'autofill@example.com',
        scene: 'register',
      });
    });
  });

  it('自动填充的非法格式仍被拒绝', async () => {
    const user = userEvent.setup();
    renderPage();

    const input = screen.getByPlaceholderText(
      '请输入手机号或邮箱',
    ) as HTMLInputElement;
    autofill(input, 'not-an-email');

    await user.click(screen.getByRole('button', { name: /获取验证码/ }));

    await waitFor(() => {
      expect(mockSendCode).not.toHaveBeenCalled();
    });
  });

  it('真为空时提示请填写', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: /获取验证码/ }));

    await waitFor(() => {
      expect(mockSendCode).not.toHaveBeenCalled();
    });
  });
});
