/**
 * B 端路由守卫。
 *
 * 仅做导航控制；真正的身份认证与权限校验由后端执行
 * （见 CLAUDE.md 前端规范第 8 条）。
 *
 * **必须等会话恢复完成再判断**：Access Token 存内存，刷新页面后
 * 内存清空，但 Refresh Token 还在 Cookie 里。若不等 `/auth/refresh`
 * 返回就判未登录，每次刷新页面都会把已登录的管理员踢回登录页。
 */
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { Spin } from 'antd';

import { useAdminAuthBootstrap } from '@/hooks/useAdminAuthBootstrap';
import { useAdminAuthStore } from '@/stores/auth';

export function RequireAdmin() {
  const location = useLocation();
  const isAuthenticated = useAdminAuthStore((state) => Boolean(state.accessToken));
  const { isLoading } = useAdminAuthBootstrap();

  if (isLoading) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Spin size="large" tip="正在恢复会话..." />
      </div>
    );
  }

  if (!isAuthenticated) {
    // 带上来源路径，登录后可直接回到原页面
    const redirect = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?redirect=${redirect}`} replace />;
  }

  return <Outlet />;
}
