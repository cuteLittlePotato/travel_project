/**
 * 顶部导航的测试。
 *
 * 重点：头像下拉菜单（个人中心 / 退出登录）。
 *
 * 设计理由：退出登录是高频操作，若头像直接跳个人中心，
 * 用户要「头像 → 个人中心 → 退出」走三步。下拉菜单把它降到两步。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App as AntdApp, ConfigProvider } from 'antd';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import zhCN from 'antd/locale/zh_CN';

import { SiteHeader } from './SiteHeader';
import { useAuthStore } from '@/stores/auth';

const mockLogout = vi.fn();
const mockPush = vi.fn();

vi.mock('@/services/auth', async () => {
  const actual = await vi.importActual<typeof import('@/services/auth')>(
    '@/services/auth',
  );
  return {
    ...actual,
    logout: (...args: unknown[]) => mockLogout(...args),
  };
});

vi.mock('next/navigation', () => ({
  usePathname: () => '/',
  useRouter: () => ({ push: mockPush, replace: vi.fn() }),
}));

vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock('@/components/notification/NotificationBell', () => ({
  NotificationBell: () => <div data-testid="notification-bell" />,
}));

function renderHeader() {
  // useLogout 内部用到 QueryClient（退出后清空缓存）
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={zhCN}>
        <AntdApp>
          <SiteHeader />
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>,
  );
}

describe('SiteHeader', () => {
  beforeEach(() => {
    mockLogout.mockReset();
    mockLogout.mockResolvedValue(undefined);
    mockPush.mockReset();
    useAuthStore.setState({ accessToken: null, user: null });
  });

  describe('未登录', () => {
    it('显示登录与注册按钮', () => {
      renderHeader();

      expect(screen.getByText(/登\s*录/)).toBeInTheDocument();
      expect(screen.getByText(/注\s*册/)).toBeInTheDocument();
    });

    it('不显示头像与通知铃', () => {
      renderHeader();

      expect(screen.queryByLabelText('账号菜单')).not.toBeInTheDocument();
      expect(screen.queryByTestId('notification-bell')).not.toBeInTheDocument();
    });
  });

  describe('已登录 —— 头像下拉菜单', () => {
    beforeEach(() => {
      useAuthStore.setState({
        accessToken: 'token',
        user: {
          user_id: 'u1',
          nickname: '测试用户',
          avatar_url: null,
        },
      });
    });

    it('显示头像与通知铃', () => {
      renderHeader();

      expect(screen.getByLabelText('账号菜单')).toBeInTheDocument();
      expect(screen.getByTestId('notification-bell')).toBeInTheDocument();
    });

    it('**点击头像不直接跳转，而是展开菜单**', async () => {
      const user = userEvent.setup();
      renderHeader();

      await user.click(screen.getByLabelText('账号菜单'));

      await waitFor(() => {
        expect(screen.getByText('个人中心')).toBeInTheDocument();
      });
      expect(screen.getByText('退出登录')).toBeInTheDocument();
      // 未跳转
      expect(mockPush).not.toHaveBeenCalled();
    });

    it('菜单顶部显示当前账号昵称', async () => {
      const user = userEvent.setup();
      renderHeader();

      await user.click(screen.getByLabelText('账号菜单'));

      await waitFor(() => {
        expect(screen.getByText('测试用户')).toBeInTheDocument();
      });
    });

    it('点击「个人中心」跳转 /profile', async () => {
      const user = userEvent.setup();
      renderHeader();

      await user.click(screen.getByLabelText('账号菜单'));
      await waitFor(() => {
        expect(screen.getByText('个人中心')).toBeInTheDocument();
      });

      await user.click(screen.getByText('个人中心'));

      expect(mockPush).toHaveBeenCalledWith('/profile');
    });

    it('点击「退出登录」弹出二次确认', async () => {
      const user = userEvent.setup();
      renderHeader();

      await user.click(screen.getByLabelText('账号菜单'));
      await waitFor(() => {
        expect(screen.getByText('退出登录')).toBeInTheDocument();
      });

      await user.click(screen.getByText('退出登录'));

      await waitFor(() => {
        expect(screen.getByText('确定要退出登录吗？')).toBeInTheDocument();
      });
      // 未确认前不调用接口
      expect(mockLogout).not.toHaveBeenCalled();
    });

    it('确认后调用退出接口并清空状态', async () => {
      const user = userEvent.setup();
      renderHeader();

      await user.click(screen.getByLabelText('账号菜单'));
      await waitFor(() => {
        expect(screen.getByText('退出登录')).toBeInTheDocument();
      });
      await user.click(screen.getByText('退出登录'));
      await waitFor(() => {
        expect(screen.getByText('确定要退出登录吗？')).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /退\s*出/ }));

      await waitFor(() => {
        expect(mockLogout).toHaveBeenCalled();
      });
      await waitFor(() => {
        expect(useAuthStore.getState().accessToken).toBeNull();
      });
    });

    it('取消确认时不退出', async () => {
      const user = userEvent.setup();
      renderHeader();

      await user.click(screen.getByLabelText('账号菜单'));
      await waitFor(() => {
        expect(screen.getByText('退出登录')).toBeInTheDocument();
      });
      await user.click(screen.getByText('退出登录'));
      await waitFor(() => {
        expect(screen.getByText('确定要退出登录吗？')).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /取\s*消/ }));

      expect(mockLogout).not.toHaveBeenCalled();
      expect(useAuthStore.getState().accessToken).toBe('token');
    });

    it('**后端退出失败时仍清空本地状态**', async () => {
      mockLogout.mockRejectedValue(new Error('网络异常'));
      const user = userEvent.setup();
      renderHeader();

      await user.click(screen.getByLabelText('账号菜单'));
      await waitFor(() => {
        expect(screen.getByText('退出登录')).toBeInTheDocument();
      });
      await user.click(screen.getByText('退出登录'));
      await waitFor(() => {
        expect(screen.getByText('确定要退出登录吗？')).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /退\s*出/ }));

      // 网络异常也必须能退出——否则用户卡在「点了没反应」
      await waitFor(() => {
        expect(useAuthStore.getState().accessToken).toBeNull();
      });
    });
  });

  describe('导航项', () => {
    it('渲染五个主导航', () => {
      renderHeader();

      for (const label of ['首页', '发现', '智能规划', '我的计划', '我的足迹']) {
        expect(screen.getByText(label)).toBeInTheDocument();
      }
    });

    it('当前路径高亮', () => {
      renderHeader();
      // usePathname mock 返回 '/'，首页应高亮
      const home = screen.getByText('首页');
      expect(home).toHaveStyle({ color: '#1677ff' });
    });
  });
});
