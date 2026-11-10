/**
 * 登录页「获取验证码」的边界测试。
 *
 * 真实问题：浏览器自动填充（Chrome autofill）只设置 DOM 的 value，
 * **不触发 React 的 onChange**，因此 antd Form 的 store 里是空的。
 * 用户看到输入框里有邮箱，点「获取验证码」却提示「请输入手机号或邮箱」。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import LoginPage from './page';

const mockSendCode = vi.fn();

vi.mock('@/services/auth', async () => {
  const actual = await vi.importActual<typeof import('@/services/auth')>(
    '@/services/auth',
  );
  return {
    ...actual,
    sendVerificationCode: (...args: unknown[]) => mockSendCode(...args),
    login: vi.fn(),
    loginByCode: vi.fn(),
  };
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={zhCN}>
        <AntdApp>
          <LoginPage />
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>,
  );
}

/** 切到验证码登录 tab */
async function switchToCodeLogin(user: ReturnType<typeof userEvent.setup>) {
  // Segmented 的可点区域是 label，点文本即可
  const tab = screen.getByText('验证码登录');
  await user.click(tab);
  await waitFor(
    () => {
      expect(screen.queryByPlaceholderText('6 位验证码')).not.toBeNull();
    },
    { timeout: 3000 },
  );
}

describe('获取验证码 —— 浏览器自动填充场景', () => {
  beforeEach(() => {
    mockSendCode.mockReset();
    mockSendCode.mockResolvedValue({ expires_in: 300, debug_code: '123456' });
  });

  it('手动输入时正常发送', async () => {
    const user = userEvent.setup();
    renderPage();
    await switchToCodeLogin(user);

    const input = screen.getByPlaceholderText('请输入手机号或邮箱') as HTMLInputElement;
    await user.type(input, 'user@example.com');
    console.error('INPUT_VALUE=' + input.value);

    const forms = document.querySelectorAll('form');
    console.error('FORM_COUNT=' + forms.length);
    const parentForm = input.closest('form');
    console.error('INPUT_IN_FORM=' + (parentForm ? 'yes' : 'NO'));
    if (parentForm) {
      const names = Array.from(parentForm.querySelectorAll('input')).map(
        (i) => (i as HTMLInputElement).placeholder,
      );
      console.error('FORM_INPUTS=' + JSON.stringify(names));
    }

    await user.click(screen.getByRole('button', { name: /获取验证码/ }));

    await waitFor(() => {
      expect(mockSendCode).toHaveBeenCalledWith({
        target: 'user@example.com',
        scene: 'login',
      });
    });
  });

  it('**自动填充只改 DOM 时也能发送**', async () => {
    const user = userEvent.setup();
    renderPage();
    await switchToCodeLogin(user);

    // 模拟 Chrome autofill：直接设置 DOM value，不触发 React onChange。
    // 这正是用户看到「框里有值但提示请填写」的原因。
    const input = screen.getByPlaceholderText(
      '请输入手机号或邮箱',
    ) as HTMLInputElement;
    const nativeSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      'value',
    )?.set;
    nativeSetter?.call(input, 'autofill@example.com');

    await user.click(screen.getByRole('button', { name: /获取验证码/ }));

    await waitFor(() => {
      expect(mockSendCode).toHaveBeenCalledWith({
        target: 'autofill@example.com',
        scene: 'login',
      });
    });
  });

  it('自动填充的值能被正常校验（拒绝非法格式）', async () => {
    const user = userEvent.setup();
    renderPage();
    await switchToCodeLogin(user);

    const input = screen.getByPlaceholderText(
      '请输入手机号或邮箱',
    ) as HTMLInputElement;
    const nativeSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      'value',
    )?.set;
    nativeSetter?.call(input, 'not-an-email');

    await user.click(screen.getByRole('button', { name: /获取验证码/ }));

    await waitFor(() => {
      expect(screen.getByText('邮箱格式不正确')).toBeInTheDocument();
    });
    expect(mockSendCode).not.toHaveBeenCalled();
  });

  it('真为空时仍提示请填写', async () => {
    const user = userEvent.setup();
    renderPage();
    await switchToCodeLogin(user);

    await user.click(screen.getByRole('button', { name: /获取验证码/ }));

    await waitFor(() => {
      expect(screen.getByText('请输入手机号或邮箱')).toBeInTheDocument();
    });
    expect(mockSendCode).not.toHaveBeenCalled();
  });
});
