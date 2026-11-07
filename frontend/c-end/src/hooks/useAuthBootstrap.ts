'use client';

/**
 * 登录态探测。
 *
 * 评审 §Q1 决策：SSR 首屏不查询登录状态，客户端 hydrate 后由本 Hook
 * 用 httpOnly Cookie 中的 Refresh Token 换取 Access Token。
 */
import { useEffect } from 'react';
import axios from 'axios';

import { useAuthStore, type AuthUser } from '@/stores/auth';
import { env } from '@/lib/utils/env';
import type { ApiResponse } from '@/types/api';

interface RefreshResult {
  access_token: string;
  user: AuthUser;
}

export function useAuthBootstrap(): void {
  const setSession = useAuthStore((state) => state.setSession);
  const setHydrated = useAuthStore((state) => state.setHydrated);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      try {
        const { data } = await axios.post<ApiResponse<RefreshResult>>(
          `${env.apiBaseUrl}/api/v1/auth/refresh`,
          {},
          { withCredentials: true, timeout: 8000 },
        );
        if (!cancelled && data.code === 0 && data.data) {
          setSession(data.data.access_token, data.data.user);
          return;
        }
      } catch {
        // 未登录属于正常路径，不提示
      }
      if (!cancelled) {
        setHydrated(true);
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [setSession, setHydrated]);
}
