/**
 * 路由守卫的测试（M01-T19 DoD）。
 *
 * DoD：未登录访问 /plans 跳转 /login
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import { RequireAuth } from './RequireAuth';
import { useAuthStore } from '@/stores/auth';

const mockReplace = vi.fn();
const mockPathname = vi.fn(() => '/plans');

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mockReplace, push: vi.fn(), back: vi.fn() }),
  usePathname: () => mockPathname(),
  useSearchParams: () => new URLSearchParams(),
}));

describe('RequireAuth', () => {
  beforeEach(() => {
    mockReplace.mockReset();
    mockPathname.mockReturnValue('/plans');
    useAuthStore.setState({ accessToken: null, user: null, hydrated: false });
  });

  afterEach(() => {
    useAuthStore.setState({ accessToken: null, user: null, hydrated: false });
  });

  it('**hydrated 前不跳转，显示加载态**', () => {
    render(
      <RequireAuth>
        <div>受保护内容</div>
      </RequireAuth>,
    );

    expect(mockReplace).not.toHaveBeenCalled();
    expect(screen.queryByText('受保护内容')).not.toBeInTheDocument();
  });

  it('**探测完成且未登录 → 跳转 /login 并带 redirect**', async () => {
    useAuthStore.setState({ hydrated: true, accessToken: null });

    render(
      <RequireAuth>
        <div>受保护内容</div>
      </RequireAuth>,
    );

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith('/login?redirect=%2Fplans');
    });
    expect(screen.queryByText('受保护内容')).not.toBeInTheDocument();
  });

  it('**已登录 → 渲染内容，不跳转**', async () => {
    useAuthStore.setState({ hydrated: true, accessToken: 'valid-token' });

    render(
      <RequireAuth>
        <div>受保护内容</div>
      </RequireAuth>,
    );

    await waitFor(() => {
      expect(screen.getByText('受保护内容')).toBeInTheDocument();
    });
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it('不同路径的 redirect 参数正确编码', async () => {
    mockPathname.mockReturnValue('/footprints');
    useAuthStore.setState({ hydrated: true, accessToken: null });

    render(
      <RequireAuth>
        <div>内容</div>
      </RequireAuth>,
    );

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith('/login?redirect=%2Ffootprints');
    });
  });

  it('未登录时不渲染任何受保护内容（避免闪现）', () => {
    useAuthStore.setState({ hydrated: true, accessToken: null });

    const { container } = render(
      <RequireAuth>
        <div>敏感内容</div>
      </RequireAuth>,
    );

    expect(container.textContent).not.toContain('敏感内容');
  });
});
