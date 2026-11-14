/**
 * 通知铃铛的组件测试（M01-T18 DoD）。
 *
 * DoD：「未读数轮询或进入页面时刷新」「标记已读后角标数字减少」
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntdApp } from 'antd';

import { NotificationBell, POLL_INTERVAL_MS } from './NotificationBell';
import { useAuthStore } from '@/stores/auth';

const mockGetUnreadCount = vi.fn();

vi.mock('@/services/notification', async () => {
  const actual = await vi.importActual<typeof import('@/services/notification')>(
    '@/services/notification',
  );
  return {
    ...actual,
    getUnreadCount: () => mockGetUnreadCount(),
  };
});

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AntdApp>{ui}</AntdApp>
    </QueryClientProvider>,
  );
}

describe('NotificationBell', () => {
  beforeEach(() => {
    mockGetUnreadCount.mockReset();
    useAuthStore.setState({ accessToken: 'test-token', user: null, hydrated: true });
  });

  afterEach(() => {
    useAuthStore.setState({ accessToken: null, user: null, hydrated: false });
  });

  it('未登录时不渲染', () => {
    useAuthStore.setState({ accessToken: null, user: null, hydrated: true });
    const { container } = renderWithProviders(<NotificationBell />);
    expect(container.querySelector('button')).toBeNull();
  });

  it('已登录时渲染铃铛', async () => {
    mockGetUnreadCount.mockResolvedValue(0);

    renderWithProviders(<NotificationBell />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /通知/ })).toBeInTheDocument();
    });
  });

  it('**未读数超过 0 时显示角标**', async () => {
    mockGetUnreadCount.mockResolvedValue(5);

    renderWithProviders(<NotificationBell />);

    await waitFor(() => {
      expect(screen.getByText('5')).toBeInTheDocument();
    });
  });

  it('未读数为 0 时不显示角标数字', async () => {
    mockGetUnreadCount.mockResolvedValue(0);

    renderWithProviders(<NotificationBell />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: '通知' })).toBeInTheDocument();
    });
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('aria-label 包含未读数量（可访问性）', async () => {
    mockGetUnreadCount.mockResolvedValue(3);

    renderWithProviders(<NotificationBell />);

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: '通知，3 条未读' }),
      ).toBeInTheDocument();
    });
  });

  it('只调用一次未读数接口（挂载时）', async () => {
    mockGetUnreadCount.mockResolvedValue(2);

    renderWithProviders(<NotificationBell />);

    await waitFor(() => {
      expect(mockGetUnreadCount).toHaveBeenCalledTimes(1);
    });
  });

  it('轮询间隔为 60 秒', () => {
    expect(POLL_INTERVAL_MS).toBe(60_000);
  });

  it('接口失败时不崩溃', async () => {
    mockGetUnreadCount.mockRejectedValue(new Error('network'));

    renderWithProviders(<NotificationBell />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: '通知' })).toBeInTheDocument();
    });
  });
});
