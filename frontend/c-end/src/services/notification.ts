/**
 * 通知服务（API §3.15 ~ §3.18）。
 */
import { http, parseApiError } from '@/lib/api/http';
import type { ApiResponse, PageData } from '@/types/api';

export type NotificationType = 'plan_starting' | 'plan_ended' | 'system';

export interface NotificationItem {
  id: string;
  notification_type: NotificationType;
  title: string;
  content: string | null;
  related_type: string | null;
  related_id: string | null;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
}

export interface NotificationListResult extends PageData<NotificationItem> {
  /** 全账号未读数，不受筛选条件影响 */
  unread_count: number;
}

export interface ListNotificationsParams {
  page?: number;
  page_size?: number;
  is_read?: boolean;
  notification_type?: NotificationType;
}

export class NotificationApiError extends Error {
  constructor(
    readonly code: number,
    message: string,
  ) {
    super(message);
    this.name = 'NotificationApiError';
  }
}

async function unwrap<T>(request: Promise<{ data: ApiResponse<T> }>): Promise<T> {
  try {
    const { data } = await request;
    if (data.code !== 0) {
      throw new NotificationApiError(data.code, data.message);
    }
    return data.data as T;
  } catch (error) {
    if (error instanceof NotificationApiError) throw error;
    const parsed = parseApiError(error);
    throw new NotificationApiError(parsed.code, parsed.message);
  }
}

export function listNotifications(
  params: ListNotificationsParams = {},
): Promise<NotificationListResult> {
  return unwrap(
    http.get<ApiResponse<NotificationListResult>>('/api/v1/notifications', {
      params,
    }),
  );
}

export function getUnreadCount(): Promise<number> {
  return unwrap(
    http.get<ApiResponse<{ count: number }>>('/api/v1/notifications/unread-count'),
  ).then((data) => data.count);
}

export async function markRead(notificationId: string): Promise<void> {
  await unwrap<null>(
    http.patch<ApiResponse<null>>(`/api/v1/notifications/${notificationId}/read`),
  );
}

export function markAllRead(): Promise<number> {
  return unwrap(
    http.post<ApiResponse<{ updated_count: number }>>(
      '/api/v1/notifications/read-all',
    ),
  ).then((data) => data.updated_count);
}

/**
 * 通知类型 → 跳转路径。
 *
 * `related_type` 是后端定义的业务类型，`related_id` 是资源 ID。
 * 类型未知时返回 null，由调用方降级处理（不跳转）。
 *
 * 注意：`related_id` 对应的资源可能已被删除，
 * 跳转后目标页面应自行处理 404（当前各页面渲染占位，不会崩溃）。
 */
export function resolveNotificationPath(item: NotificationItem): string | null {
  if (!item.related_type || !item.related_id) return null;

  const routes: Record<string, (id: string) => string> = {
    plan: (id) => `/plans?highlight=${id}`,
    trip_plan: (id) => `/plans?highlight=${id}`,
    footprint: (id) => `/footprints?highlight=${id}`,
    attraction: (id) => `/attraction/${id}`,
  };

  const builder = routes[item.related_type];
  return builder ? builder(item.related_id) : null;
}
