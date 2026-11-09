/**
 * 通知服务的契约测试（M01-T18）。
 *
 * 重点：`resolveNotificationPath` 的映射与降级逻辑（DoD 要求）。
 */
import { describe, expect, it } from 'vitest';

import { formatTime } from '@/components/notification/NotificationList';
import { resolveNotificationPath, type NotificationItem } from './notification';

function makeItem(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    id: 'n1',
    notification_type: 'system',
    title: '标题',
    content: '内容',
    related_type: null,
    related_id: null,
    is_read: false,
    read_at: null,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

describe('resolveNotificationPath', () => {
  it('plan → /plans?highlight=id', () => {
    expect(resolveNotificationPath(makeItem({ related_type: 'plan', related_id: 'p1' }))).toBe(
      '/plans?highlight=p1',
    );
  });

  it('trip_plan 与 plan 等效', () => {
    expect(
      resolveNotificationPath(makeItem({ related_type: 'trip_plan', related_id: 'p2' })),
    ).toBe('/plans?highlight=p2');
  });

  it('footprint → /footprints?highlight=id', () => {
    expect(
      resolveNotificationPath(makeItem({ related_type: 'footprint', related_id: 'f1' })),
    ).toBe('/footprints?highlight=f1');
  });

  it('attraction → /attraction/id', () => {
    expect(
      resolveNotificationPath(makeItem({ related_type: 'attraction', related_id: 'a1' })),
    ).toBe('/attraction/a1');
  });

  it('**related_type 为空时返回 null**（降级，不跳转）', () => {
    expect(resolveNotificationPath(makeItem({ related_type: null }))).toBeNull();
  });

  it('**related_id 为空时返回 null**', () => {
    expect(resolveNotificationPath(makeItem({ related_type: 'plan' }))).toBeNull();
  });

  it('**未知 related_type 返回 null**，不拼接出错误路径', () => {
    expect(
      resolveNotificationPath(makeItem({ related_type: 'unknown_type', related_id: 'x' })),
    ).toBeNull();
  });

  it('系统通知（无关联）不跳转', () => {
    expect(resolveNotificationPath(makeItem({ notification_type: 'system' }))).toBeNull();
  });
});

describe('formatTime', () => {
  it('1 分钟内显示「刚刚」', () => {
    const now = new Date();
    expect(formatTime(now.toISOString())).toBe('刚刚');
  });

  it('N 分钟前', () => {
    const date = new Date(Date.now() - 5 * 60_000);
    expect(formatTime(date.toISOString())).toBe('5 分钟前');
  });

  it('N 小时前', () => {
    const date = new Date(Date.now() - 3 * 3600_000);
    expect(formatTime(date.toISOString())).toBe('3 小时前');
  });

  it('N 天前', () => {
    const date = new Date(Date.now() - 2 * 86400_000);
    expect(formatTime(date.toISOString())).toBe('2 天前');
  });

  it('超过 7 天显示日期', () => {
    const date = new Date(Date.now() - 10 * 86400_000);
    const result = formatTime(date.toISOString());
    expect(result).not.toContain('天前');
    expect(result).toMatch(/\d{4}/);
  });
});
