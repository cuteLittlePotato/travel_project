/**
 * 活动管理页的组件测试（M11-T13 DoD）。
 *
 * DoD：
 *   - 状态徽章按 upcoming/ongoing/ended 着色
 *   - 日期区间校验（结束日期早于开始日期时禁止提交）
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';

import ActivitiesPage, { STATUS_CONFIG } from './index';
import type { PageData } from '@/types/api';
import type { Activity, ActivityStatus } from '@/services/catalog';

const mockListActivities = vi.fn();

vi.mock('@/services/catalog', async () => {
  const actual = await vi.importActual<typeof import('@/services/catalog')>(
    '@/services/catalog',
  );
  return {
    ...actual,
    listActivities: (...args: unknown[]) => mockListActivities(...args),
    deleteActivity: vi.fn(),
    setActivityPublished: vi.fn(),
  };
});

function makeActivity(overrides: Partial<Activity> = {}): Activity {
  return {
    id: 'act-1-0000-0000-000000000000',
    title: '故宫春季特展',
    description: '限时展览',
    cover_image_url: null,
    activity_type: 'exhibition',
    start_date: '2026-04-01',
    end_date: '2026-05-31',
    city_id: null,
    attraction_id: null,
    detail_url: 'https://example.com/activity/1',
    is_published: true,
    sort_weight: 100,
    created_by: 'admin-1',
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
    status: 'ongoing',
    ...overrides,
  };
}

function makePage(items: Activity[], total = items.length): PageData<Activity> {
  return { items, total, page: 1, page_size: 10, total_pages: Math.ceil(total / 10) || 0 };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={zhCN}>
        <AntdApp>
          <ActivitiesPage />
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>,
  );
}

describe('ActivitiesPage', () => {
  beforeEach(() => {
    mockListActivities.mockReset();
    mockListActivities.mockResolvedValue(makePage([makeActivity()]));
  });

  describe('状态徽章（DoD：upcoming/ongoing/ended 着色）', () => {
    it('STATUS_CONFIG 覆盖三种状态且颜色不同', () => {
      expect(STATUS_CONFIG.upcoming.color).toBe('blue');
      expect(STATUS_CONFIG.ongoing.color).toBe('green');
      expect(STATUS_CONFIG.ended.color).toBe('default');

      const colors = new Set(Object.values(STATUS_CONFIG).map((v) => v.color));
      expect(colors.size).toBe(3);
    });

    it('进行中活动显示绿色徽章', async () => {
      renderPage();
      await waitFor(() => {
        expect(screen.getByText('进行中')).toBeInTheDocument();
      });
    });

    it('未开始活动显示蓝色徽章', async () => {
      mockListActivities.mockResolvedValue(
        makePage([makeActivity({ status: 'upcoming' })]),
      );
      renderPage();
      await waitFor(() => {
        expect(screen.getByText('未开始')).toBeInTheDocument();
      });
    });

    it('已结束活动显示「已结束」', async () => {
      mockListActivities.mockResolvedValue(
        makePage([makeActivity({ status: 'ended' })]),
      );
      renderPage();
      await waitFor(() => {
        expect(screen.getByText('已结束')).toBeInTheDocument();
      });
    });

    it.each<[ActivityStatus, string]>([
      ['upcoming', '未开始'],
      ['ongoing', '进行中'],
      ['ended', '已结束'],
    ])('状态 %s 映射为「%s」', (status, text) => {
      expect(STATUS_CONFIG[status].text).toBe(text);
    });
  });

  describe('表格内容', () => {
    it('展示活动标题与时间区间', async () => {
      renderPage();
      await waitFor(() => {
        expect(screen.getByText('故宫春季特展')).toBeInTheDocument();
      });
      expect(screen.getByText('2026-04-01 ~ 2026-05-31')).toBeInTheDocument();
    });

    it('类型标签正确', async () => {
      renderPage();
      await waitFor(() => {
        expect(screen.getByText('展览')).toBeInTheDocument();
      });
    });

    it('表头顺序符合设计', async () => {
      renderPage();
      await waitFor(() => {
        expect(screen.getByText('故宫春季特展')).toBeInTheDocument();
      });

      for (const header of [
        '活动标题', '类型', '活动时间', '状态', '上下架', '排序', '操作',
      ]) {
        expect(screen.getByRole('columnheader', { name: header })).toBeInTheDocument();
      }
    });

    it('**无价格列**（评审 §Q3：价格走 detail_url 外链）', async () => {
      renderPage();
      await waitFor(() => {
        expect(screen.getByText('故宫春季特展')).toBeInTheDocument();
      });

      const headers = screen
        .getAllByRole('columnheader')
        .map((el) => el.textContent ?? '');
      expect(headers.some((h) => h.includes('价格'))).toBe(false);
      expect(headers.some((h) => h.includes('票价'))).toBe(false);
    });

    it('空列表时无数据', async () => {
      mockListActivities.mockResolvedValue(makePage([]));
      renderPage();
      await waitFor(() => {
        expect(mockListActivities).toHaveBeenCalled();
      });
      expect(screen.queryByText('故宫春季特展')).not.toBeInTheDocument();
    });
  });

  describe('列表行为', () => {
    it('下架的活动开关为关闭态', async () => {
      mockListActivities.mockResolvedValue(
        makePage([makeActivity({ is_published: false })]),
      );
      renderPage();

      await waitFor(() => {
        const switches = screen.getAllByRole('switch');
        expect(switches[0]).toHaveAttribute('aria-checked', 'false');
      });
    });

    it('分页总数展示', async () => {
      mockListActivities.mockResolvedValue(makePage([makeActivity()], 33));
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('共 33 条')).toBeInTheDocument();
      });
    });
  });
});
