'use client';

/**
 * 通知列表（M01-T18）。
 *
 * 分页加载（边界：大量通知），点击单条标记已读并跳转。
 * `related_id` 对应资源已删除时的降级：仍标记已读，但不跳转而是提示。
 */
import { useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { App, Button, Empty, List, Spin, Tag, Typography } from 'antd';
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import {
  NotificationApiError,
  listNotifications,
  markAllRead,
  markRead,
  resolveNotificationPath,
  type NotificationItem,
  type NotificationType,
} from '@/services/notification';

const PAGE_SIZE = 20;

const TYPE_LABEL: Record<NotificationType, { text: string; color: string }> = {
  plan_starting: { text: '计划提醒', color: 'blue' },
  plan_ended: { text: '计划结束', color: 'green' },
  system: { text: '系统通知', color: 'default' },
};

export interface NotificationListProps {
  /** 列表数据变化时回调（用于同步角标） */
  onChanged?: () => void;
}

export function NotificationList({ onChanged }: NotificationListProps) {
  const router = useRouter();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const loadMoreRef = useRef<HTMLDivElement>(null);

  const query = useInfiniteQuery({
    queryKey: ['notifications', 'list'],
    initialPageParam: 1,
    queryFn: ({ pageParam }) =>
      listNotifications({ page: pageParam, page_size: PAGE_SIZE }),
    getNextPageParam: (lastPage) =>
      lastPage.page < lastPage.total_pages ? lastPage.page + 1 : undefined,
  });

  // 滚动到底部自动加载（大量通知）
  useEffect(() => {
    const node = loadMoreRef.current;
    if (!node || !query.hasNextPage) return;

    const observer = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting && !query.isFetchingNextPage) {
        void query.fetchNextPage();
      }
    });

    observer.observe(node);
    return () => observer.disconnect();
  }, [query]);

  const markReadMutation = useMutation({
    mutationFn: markRead,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['notifications'] });
      onChanged?.();
    },
  });

  const markAllMutation = useMutation({
    mutationFn: markAllRead,
    onSuccess: (count) => {
      message.success(count > 0 ? `已将 ${count} 条通知标为已读` : '没有未读通知');
      void queryClient.invalidateQueries({ queryKey: ['notifications'] });
      onChanged?.();
    },
  });

  const handleClick = async (item: NotificationItem) => {
    // 先标记已读（即使跳转失败，用户确实看过这条）
    if (!item.is_read) {
      try {
        await markReadMutation.mutateAsync(item.id);
      } catch (error) {
        if (error instanceof NotificationApiError) {
          message.warning(error.message);
        }
      }
    }

    const path = resolveNotificationPath(item);
    if (!path) {
      // 降级：关联资源类型未知或已删除，不跳转
      message.info('关联内容已不存在');
      return;
    }
    router.push(path);
  };

  const items = query.data?.pages.flatMap((page) => page.items) ?? [];
  const unreadCount = query.data?.pages[0]?.unread_count ?? 0;

  if (query.isLoading) {
    return (
      <div style={{ padding: 32, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }

  if (items.length === 0) {
    return <Empty description="暂无通知" style={{ padding: 32 }} />;
  }

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '8px 16px',
          borderBottom: '1px solid #f0f0f0',
        }}
      >
        <Typography.Text type="secondary">
          {unreadCount > 0 ? `${unreadCount} 条未读` : '全部已读'}
        </Typography.Text>
        <Button
          type="link"
          size="small"
          disabled={unreadCount === 0}
          loading={markAllMutation.isPending}
          onClick={() => markAllMutation.mutate()}
        >
          全部已读
        </Button>
      </div>

      <List
        dataSource={items}
        style={{ maxHeight: 480, overflowY: 'auto' }}
        renderItem={(item) => {
          const typeMeta = TYPE_LABEL[item.notification_type] ?? {
            text: item.notification_type,
            color: 'default',
          };
          return (
            <List.Item
              key={item.id}
              onClick={() => void handleClick(item)}
              style={{
                cursor: 'pointer',
                padding: '12px 16px',
                background: item.is_read ? undefined : '#f6faff',
              }}
            >
              <List.Item.Meta
                title={
                  <span>
                    {!item.is_read && (
                      <span
                        style={{
                          display: 'inline-block',
                          width: 6,
                          height: 6,
                          borderRadius: '50%',
                          background: '#1677ff',
                          marginRight: 8,
                          verticalAlign: 'middle',
                        }}
                      />
                    )}
                    <Typography.Text strong={!item.is_read}>{item.title}</Typography.Text>
                    <Tag color={typeMeta.color} style={{ marginLeft: 8 }}>
                      {typeMeta.text}
                    </Tag>
                  </span>
                }
                description={
                  <div>
                    {item.content && (
                      <Typography.Paragraph
                        type="secondary"
                        ellipsis={{ rows: 2 }}
                        style={{ marginBottom: 4 }}
                      >
                        {item.content}
                      </Typography.Paragraph>
                    )}
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {formatTime(item.created_at)}
                    </Typography.Text>
                  </div>
                }
              />
            </List.Item>
          );
        }}
      />

      <div ref={loadMoreRef} style={{ padding: 12, textAlign: 'center' }}>
        {query.isFetchingNextPage && <Spin size="small" />}
        {!query.hasNextPage && items.length > PAGE_SIZE && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            没有更多了
          </Typography.Text>
        )}
      </div>
    </div>
  );
}

/** 相对时间：刚刚 / N 分钟前 / N 小时前 / 日期 */
export function formatTime(iso: string): string {
  const date = new Date(iso);
  const diffMs = Date.now() - date.getTime();
  const diffMinutes = Math.floor(diffMs / 60_000);

  if (diffMinutes < 1) return '刚刚';
  if (diffMinutes < 60) return `${diffMinutes} 分钟前`;

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours} 小时前`;

  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays} 天前`;

  return date.toLocaleDateString('zh-CN');
}
