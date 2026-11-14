'use client';

/**
 * 通知铃铛（M01-T18）。
 *
 * 未读数来源（DoD）：进入页面时刷新 + 每 60 秒轮询。
 * 只在已登录时启用——未登录轮询会持续 401。
 *
 * 点击打开抽屉，抽屉内是 `NotificationList`。
 */
import { useEffect, useState } from 'react';
import { Badge, Button, Drawer } from 'antd';
import { BellOutlined } from '@ant-design/icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { NotificationList } from '@/components/notification/NotificationList';
import { getUnreadCount } from '@/services/notification';
import { useAuthStore } from '@/stores/auth';

/** 轮询间隔（毫秒）。通知不是实时性要求高的数据，1 分钟足够 */
export const POLL_INTERVAL_MS = 60_000;

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const accessToken = useAuthStore((state) => state.accessToken);
  const queryClient = useQueryClient();

  const unreadQuery = useQuery({
    queryKey: ['notifications', 'unread-count'],
    queryFn: getUnreadCount,
    enabled: Boolean(accessToken),
    // DoD：进入页面时刷新 + 轮询
    refetchInterval: POLL_INTERVAL_MS,
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
    // 401 时不重试，避免登录失效后持续打接口
    retry: false,
  });

  // 打开抽屉时立即刷新一次，保证看到最新
  useEffect(() => {
    if (open) {
      void queryClient.invalidateQueries({ queryKey: ['notifications'] });
    }
  }, [open, queryClient]);

  if (!accessToken) return null;

  const count = unreadQuery.data ?? 0;

  return (
    <>
      <Badge count={count} size="small" offset={[-2, 2]}>
        <Button
          type="text"
          shape="circle"
          icon={<BellOutlined />}
          aria-label={count > 0 ? `通知，${count} 条未读` : '通知'}
          onClick={() => setOpen(true)}
        />
      </Badge>

      <Drawer
        title="通知"
        placement="right"
        width={420}
        open={open}
        onClose={() => setOpen(false)}
        styles={{ body: { padding: 0 } }}
      >
        <NotificationList
          onChanged={() => {
            void queryClient.invalidateQueries({
              queryKey: ['notifications', 'unread-count'],
            });
          }}
        />
      </Drawer>
    </>
  );
}
