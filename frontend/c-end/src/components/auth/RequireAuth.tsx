'use client';

/**
 * 受保护路由守卫（M01-T19）。
 *
 * 职责边界（CLAUDE.md 前端规范第 8 条）：
 *   **只做导航控制**——未登录跳转登录页。真正的身份认证与接口权限
 *   由后端执行，前端守卫不能作为安全边界。
 *
 * 关键：必须等 `hydrated` 为 true 再判断。
 * 登录态来自 httpOnly Cookie 的异步探测（`useAuthBootstrap`），
 * 若 hydration 未完成就判定「未登录」，已登录用户会看到瞬间的跳转闪烁。
 */
import { useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Spin } from 'antd';

import { useAuthStore } from '@/stores/auth';

export interface RequireAuthProps {
  children: React.ReactNode;
}

export function RequireAuth({ children }: RequireAuthProps) {
  const router = useRouter();
  const pathname = usePathname();
  const accessToken = useAuthStore((state) => state.accessToken);
  const hydrated = useAuthStore((state) => state.hydrated);

  const authenticated = Boolean(accessToken);

  useEffect(() => {
    if (!hydrated) return; // 等待登录态探测完成
    if (authenticated) return;

    // 带上原路径，登录后可跳回
    const target = pathname ? `/login?redirect=${encodeURIComponent(pathname)}` : '/login';
    router.replace(target);
  }, [hydrated, authenticated, pathname, router]);

  // 探测中：显示加载态，不渲染受保护内容也不跳转
  if (!hydrated) {
    return (
      <div
        style={{
          minHeight: '60vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Spin size="large" />
      </div>
    );
  }

  // 已确认未登录：避免闪一下内容，直接渲染空
  if (!authenticated) {
    return null;
  }

  return <>{children}</>;
}
