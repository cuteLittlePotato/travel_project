/**
 * Vitest 全局 setup。
 *
 * 主要解决 Next.js 特有 API 在 jsdom 下不可用的问题：
 *   - next/navigation 的 useRouter / useSearchParams
 *   - antd 的 matchMedia（响应式断点）
 */
import '@testing-library/jest-dom/vitest';

import { afterAll, beforeAll, vi } from 'vitest';

// antd 的响应式组件依赖 matchMedia，jsdom 不提供
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// antd 的 Cascader / Select 等组件依赖 ResizeObserver，jsdom 不提供。
// 缺了它会在挂载时抛 ReferenceError: ResizeObserver is not defined。
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

// Next.js 路由 mock。各测试可通过 vi.mocked(useRouter) 覆盖行为
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/'),
  redirect: vi.fn(),
}));

// 屏蔽 antd 在 jsdom 下的已知警告
const originalError = console.error;
beforeAll(() => {
  console.error = (...args: unknown[]) => {
    const msg = String(args[0] ?? '');
    if (msg.includes('Not implemented: window.scrollTo')) return;
    originalError(...args);
  };
});
afterAll(() => {
  console.error = originalError;
});
