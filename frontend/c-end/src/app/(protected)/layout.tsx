'use client';

/**
 * 受保护路由组布局（M01-T19）。
 *
 * Next.js 路由组 `(protected)` 不影响 URL——`/plans` 仍是 `/plans`，
 * 但组内所有页面共享这一层守卫。
 *
 * 覆盖页面：对话、计划、足迹、个人中心。
 * 公开页面（首页/详情/发现/知识图谱/登录/注册）不在此组内。
 */
import { RequireAuth } from '@/components/auth/RequireAuth';

export default function ProtectedLayout({ children }: { children: React.ReactNode }) {
  return <RequireAuth>{children}</RequireAuth>;
}
