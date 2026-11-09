'use client';

/**
 * 登录态探测（M01-T19）。
 *
 * 评审 §Q1：SSR 首屏不查询登录状态，客户端 hydrate 后用 httpOnly Cookie
 * 中的 Refresh Token 换取 Access Token。
 *
 * 流程：
 *   1. 调 `/auth/refresh`（Cookie 自动携带）→ 拿到 access_token
 *   2. 若成功，再调 `/users/me` 拿用户信息
 *   3. 任一失败 → 标记 hydrated=true，视为未登录
 *
 * **第 2 步单独请求的原因**：`/auth/refresh`（API §3.6）只返回
 * `access_token` / `refresh_token` / `expires_in`，不含用户信息。
 */
import { useEffect } from 'react';
import axios from 'axios';

import { useAuthStore, type AuthUser } from '@/stores/auth';
import { env } from '@/lib/utils/env';
import type { ApiResponse } from '@/types/api';

interface RefreshResult {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

interface MeResult {
  id: string;
  nickname: string;
  avatar_url: string | null;
}

/** 探测超时。8 秒足够，超时视为未登录而不是卡住页面 */
const BOOTSTRAP_TIMEOUT_MS = 8_000;

export function useAuthBootstrap(): void {
  const setSession = useAuthStore((state) => state.setSession);
  const setHydrated = useAuthStore((state) => state.setHydrated);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      try {
        // 1. 用 Cookie 里的 Refresh Token 换 Access Token
        const { data: refreshData } = await axios.post<ApiResponse<RefreshResult>>(
          `${env.apiBaseUrl}/api/v1/auth/refresh`,
          {},
          { withCredentials: true, timeout: BOOTSTRAP_TIMEOUT_MS },
        );

        if (refreshData.code !== 0 || !refreshData.data) {
          throw new Error('refresh failed');
        }

        const accessToken = refreshData.data.access_token;

        // 2. 拿用户信息
        const { data: meData } = await axios.get<ApiResponse<MeResult>>(
          `${env.apiBaseUrl}/api/v1/users/me`,
          {
            headers: { Authorization: `Bearer ${accessToken}` },
            timeout: BOOTSTRAP_TIMEOUT_MS,
          },
        );

        if (cancelled) return;

        // 用户信息请求失败不阻塞登录（可能是网络抖动），用占位 id
        const user: AuthUser =
          meData.code === 0 && meData.data
            ? {
                user_id: meData.data.id,
                nickname: meData.data.nickname,
                avatar_url: meData.data.avatar_url,
              }
            : { user_id: '' };

        setSession(accessToken, user);
        return;
      } catch {
        // 未登录属于正常路径，不提示也不记录错误日志
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
