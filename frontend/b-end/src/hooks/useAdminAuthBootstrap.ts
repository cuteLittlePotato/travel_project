/**
 * B 端启动时的会话恢复（M15-T09）。
 *
 * 为什么需要这一步：
 *   Access Token 存在内存里（评审 §Q1），页面刷新后内存清空，
 *   但 Refresh Token 还在 httpOnly Cookie 里。不恢复的话，
 *   管理员每刷新一次页面就要重新登录一次。
 *
 * 流程：
 *   1. 调 /auth/refresh（浏览器自动带上 Cookie）
 *   2. 成功 → 拿到新的 Access Token 与管理员信息，写入 store
 *   3. 失败 → 说明 Cookie 也失效了，静默忽略，走未登录流程
 *
 * **失败不报错**：首次访问的访客本来就没有 Cookie，
 * 弹「登录已过期」对他们是噪音。
 */
import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';

import { refreshToken } from '@/services/auth';
import { useAdminAuthStore } from '@/stores/auth';

export function useAdminAuthBootstrap() {
  const { setSession, clear, admin: currentAdmin } = useAdminAuthStore();

  const refreshQuery = useQuery({
    queryKey: ['admin-auth-bootstrap'],
    queryFn: refreshToken,
    // 只在启动时跑一次，不重试、不随窗口聚焦重新拉取
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: Infinity,
    gcTime: Infinity,
    // 已经登录（比如刚在登录页登录完）就不必再换一次 Token
    enabled: !currentAdmin,
  });

  useEffect(() => {
    if (refreshQuery.data) {
      setSession(refreshQuery.data.access_token, refreshQuery.data.admin);
    } else if (refreshQuery.isError) {
      clear();
    }
  }, [refreshQuery.data, refreshQuery.isError, setSession, clear]);

  return {
    isLoading: refreshQuery.isLoading && !currentAdmin,
    isError: refreshQuery.isError,
  };
}
