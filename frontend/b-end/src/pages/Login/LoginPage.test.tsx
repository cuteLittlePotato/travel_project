/**
 * B 端登录页的组件测试（M15-T09）。
 *
 * 覆盖：
 *   - 表单校验（必填、账号长度）
 *   - 登录成功后写入 store 并跳转
 *   - 登录失败展示后端错误文案
 *   - 开放重定向防护（只接受站内相对路径）
 *   - 已登录时自动跳走
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { LoginPage } from './index';
import { useAdminAuthStore, type AdminUser } from '@/stores/auth';

const mockLogin = vi.fn();

vi.mock('@/services/auth', async () => {
  const actual = await vi.importActual<typeof import('@/services/auth')>(
    '@/services/auth',
  );
  return {
    ...actual,
    login: (...args: unknown[]) => mockLogin(...args),
    refreshToken: vi.fn().mockRejectedValue(new Error('no cookie')),
  };
});

const ADMIN: AdminUser = {
  id: 'admin-1',
  username: 'admin',
  real_name: '超级管理员',
  roles: [{ id: 'role-1', code: 'super_admin', name: '超级管理员' }],
};

function renderLogin(initialPath = '/login') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={zhCN}>
        <AntdApp>
          <MemoryRouter initialEntries={[initialPath]}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/dashboard" element={<div>数据看板页面</div>} />
              <Route path="/attractions" element={<div>景点管理页面</div>} />
            </Routes>
          </MemoryRouter>
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>,
  );
}

describe('LoginPage', () => {
  beforeEach(() => {
    mockLogin.mockReset();
    useAdminAuthStore.setState({ accessToken: null, admin: null, hydrated: false });
  });

  describe('表单校验', () => {
    it('账号和密码都为空时提示', async () => {
      const user = userEvent.setup();
      renderLogin();

      await user.click(screen.getByRole('button', { name: /登\s*录/ }));

      await waitFor(() => {
        expect(screen.getByText('请输入账号')).toBeInTheDocument();
      });
      expect(screen.getByText('请输入密码')).toBeInTheDocument();
    });

    it('账号太短时提示', async () => {
      const user = userEvent.setup();
      renderLogin();

      await user.type(screen.getByPlaceholderText('请输入账号'), 'ab');
      await user.click(screen.getByRole('button', { name: /登\s*录/ }));

      await waitFor(() => {
        expect(screen.getByText('账号长度为 3-50 字符')).toBeInTheDocument();
      });
    });

    it('校验失败时不发起请求', async () => {
      const user = userEvent.setup();
      renderLogin();

      await user.click(screen.getByRole('button', { name: /登\s*录/ }));

      await waitFor(() => {
        expect(screen.getByText('请输入账号')).toBeInTheDocument();
      });
      expect(mockLogin).not.toHaveBeenCalled();
    });
  });

  describe('登录成功', () => {
    it('写入 store 并跳转 dashboard', async () => {
      mockLogin.mockResolvedValue({
        access_token: 'access-token',
        refresh_token: 'refresh-token',
        token_type: 'bearer',
        expires_in: 1800,
        user_type: 'admin',
        admin: ADMIN,
      });

      const user = userEvent.setup();
      renderLogin();

      await user.type(screen.getByPlaceholderText('请输入账号'), 'admin');
      await user.type(screen.getByPlaceholderText('请输入密码'), 'Passw0rd123');
      await user.click(screen.getByRole('button', { name: /登\s*录/ }));

      await waitFor(() => {
        expect(screen.getByText('数据看板页面')).toBeInTheDocument();
      });

      const state = useAdminAuthStore.getState();
      expect(state.accessToken).toBe('access-token');
      expect(state.admin?.username).toBe('admin');
    });

    it('显示欢迎语使用 real_name', async () => {
      mockLogin.mockResolvedValue({
        access_token: 'token',
        refresh_token: 'refresh',
        token_type: 'bearer',
        expires_in: 1800,
        user_type: 'admin',
        admin: ADMIN,
      });

      const user = userEvent.setup();
      renderLogin();

      await user.type(screen.getByPlaceholderText('请输入账号'), 'admin');
      await user.type(screen.getByPlaceholderText('请输入密码'), 'Passw0rd123');
      await user.click(screen.getByRole('button', { name: /登\s*录/ }));

      await waitFor(() => {
        expect(
          screen.getByText('欢迎回来，超级管理员'),
        ).toBeInTheDocument();
      });
    });

    it('按 redirect 参数跳转', async () => {
      mockLogin.mockResolvedValue({
        access_token: 'token',
        refresh_token: 'refresh',
        token_type: 'bearer',
        expires_in: 1800,
        user_type: 'admin',
        admin: ADMIN,
      });

      const user = userEvent.setup();
      renderLogin('/login?redirect=%2Fattractions');

      await user.type(screen.getByPlaceholderText('请输入账号'), 'admin');
      await user.type(screen.getByPlaceholderText('请输入密码'), 'Passw0rd123');
      await user.click(screen.getByRole('button', { name: /登\s*录/ }));

      await waitFor(() => {
        expect(screen.getByText('景点管理页面')).toBeInTheDocument();
      });
    });
  });

  describe('登录失败', () => {
    it('展示后端返回的错误文案', async () => {
      mockLogin.mockRejectedValue(new Error('用户名或密码错误'));

      const user = userEvent.setup();
      renderLogin();

      await user.type(screen.getByPlaceholderText('请输入账号'), 'admin');
      await user.type(screen.getByPlaceholderText('请输入密码'), 'wrong');
      await user.click(screen.getByRole('button', { name: /登\s*录/ }));

      await waitFor(() => {
        expect(screen.getByText('用户名或密码错误')).toBeInTheDocument();
      });
    });

    it('失败时不写入 store', async () => {
      mockLogin.mockRejectedValue(new Error('用户名或密码错误'));

      const user = userEvent.setup();
      renderLogin();

      await user.type(screen.getByPlaceholderText('请输入账号'), 'admin');
      await user.type(screen.getByPlaceholderText('请输入密码'), 'wrong');
      await user.click(screen.getByRole('button', { name: /登\s*录/ }));

      await waitFor(() => {
        expect(screen.getByText('用户名或密码错误')).toBeInTheDocument();
      });
      expect(useAdminAuthStore.getState().accessToken).toBeNull();
    });

    it('账号禁用时展示对应文案', async () => {
      mockLogin.mockRejectedValue(new Error('账号已被禁用，请联系超级管理员'));

      const user = userEvent.setup();
      renderLogin();

      await user.type(screen.getByPlaceholderText('请输入账号'), 'banned');
      await user.type(screen.getByPlaceholderText('请输入密码'), 'Passw0rd123');
      await user.click(screen.getByRole('button', { name: /登\s*录/ }));

      await waitFor(() => {
        expect(
          screen.getByText('账号已被禁用，请联系超级管理员'),
        ).toBeInTheDocument();
      });
    });
  });

  describe('开放重定向防护', () => {
    it.each([
      ['https://evil.com', '外部绝对地址'],
      ['//evil.com', '协议相对地址'],
      ['/login', '登录页自身'],
    ])('拒绝 %s（%s）', async (redirect) => {
      mockLogin.mockResolvedValue({
        access_token: 'token',
        refresh_token: 'refresh',
        token_type: 'bearer',
        expires_in: 1800,
        user_type: 'admin',
        admin: ADMIN,
      });

      const user = userEvent.setup();
      renderLogin(`/login?redirect=${encodeURIComponent(redirect)}`);

      await user.type(screen.getByPlaceholderText('请输入账号'), 'admin');
      await user.type(screen.getByPlaceholderText('请输入密码'), 'Passw0rd123');
      await user.click(screen.getByRole('button', { name: /登\s*录/ }));

      // 应回退到 dashboard，而不是跳去外部地址
      await waitFor(() => {
        expect(screen.getByText('数据看板页面')).toBeInTheDocument();
      });
    });
  });

  describe('已登录', () => {
    it('已登录时自动跳走，不停在登录页', async () => {
      useAdminAuthStore.setState({
        accessToken: 'existing-token',
        admin: ADMIN,
      });

      renderLogin();

      await waitFor(() => {
        expect(screen.getByText('数据看板页面')).toBeInTheDocument();
      });
    });
  });
});
