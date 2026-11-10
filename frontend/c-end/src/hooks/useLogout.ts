'use client';

/**
 * 退出登录（全端）。
 *
 * 顶部导航与个人中心都要用，抽成 Hook 避免两处逻辑漂移。
 *
 * **无论后端是否成功，本地状态一律清空**：
 * 网络异常时用户仍然能退出——否则他会卡在「点了没反应」的状态里。
 * 后端残留的 Token 会因 ``token_version`` 未自增而短暂有效，
 * 但下次登录会让旧的失效。
 */
import { useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';

import { logout } from '@/services/auth';
import { useAuthStore } from '@/stores/auth';

export function useLogout() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const clear = useAuthStore((state) => state.clear);

  return useCallback(async () => {
    try {
      await logout();
    } catch {
      // 忽略：本地清理照常执行
    } finally {
      clear();
      // 清空缓存，避免下一个登录用户看到上一个用户的查询结果
      queryClient.clear();
      router.replace('/login');
    }
  }, [clear, queryClient, router]);
}
