/**
 * B 端路由守卫。
 *
 * 仅做导航控制；真正的身份认证与权限校验由后端执行
 * （见 CLAUDE.md 前端规范第 8 条）。
 */
import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { useAdminAuthStore } from '@/stores/auth';

export function RequireAdmin() {
  const location = useLocation();
  const isAuthenticated = useAdminAuthStore((state) => Boolean(state.accessToken));

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }

  return <Outlet />;
}
