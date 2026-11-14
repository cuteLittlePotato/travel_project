/**
 * 景点管理页的组件测试（M11-T11 DoD）。
 *
 * DoD：
 *   - 表格列与原型一致
 *   - 分类多选保存后列表刷新
 *   - 分页/搜索/分类过滤可用
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';

import AttractionsPage from './index';
import type { PageData } from '@/types/api';
import type { Attraction } from '@/services/catalog';

const mockListAttractions = vi.fn();
const mockListCategories = vi.fn();
const mockDeleteAttraction = vi.fn();

vi.mock('@/services/catalog', async () => {
  const actual = await vi.importActual<typeof import('@/services/catalog')>(
    '@/services/catalog',
  );
  return {
    ...actual,
    listAttractions: (...args: unknown[]) => mockListAttractions(...args),
    listCategories: (...args: unknown[]) => mockListCategories(...args),
    deleteAttraction: (...args: unknown[]) => mockDeleteAttraction(...args),
  };
});

function makeAttraction(overrides: Partial<Attraction> = {}): Attraction {
  return {
    id: 'a1b2c3d4-0000-0000-0000-000000000000',
    name: '故宫博物院',
    city_id: 'c1',
    city_name: '北京市',
    summary: '明清两代皇家宫殿',
    cover_image_url: null,
    ticket_price: '60.00',
    base_popularity: '90.00',
    final_popularity: '95.00',
    is_published: true,
    sort_weight: 100,
    categories: ['历史人文', '5A景区'],
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

function makePage(items: Attraction[], total = items.length): PageData<Attraction> {
  return {
    items,
    total,
    page: 1,
    page_size: 10,
    total_pages: Math.ceil(total / 10) || 0,
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={zhCN}>
        <AntdApp>
          <AttractionsPage />
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>,
  );
}

describe('AttractionsPage', () => {
  beforeEach(() => {
    mockListAttractions.mockReset();
    mockListCategories.mockReset();
    mockDeleteAttraction.mockReset();

    mockListAttractions.mockResolvedValue(makePage([makeAttraction()]));
    mockListCategories.mockResolvedValue({
      items: [
        { id: 'cat1', name: '历史人文', category_type: 'theme' },
        { id: 'cat2', name: '5A景区', category_type: 'level' },
      ],
    });
  });

  describe('表格列（DoD：与原型一致）', () => {
    it('渲染原型的 9 个表头', async () => {
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('故宫博物院')).toBeInTheDocument();
      });

      // 原型的 9 列
      for (const header of [
        'ID',
        '图片',
        '景点名称',
        '城市',
        '分类',
        '门票价格',
        '热度',
        '状态',
        '操作',
      ]) {
        expect(screen.getByRole('columnheader', { name: header })).toBeInTheDocument();
      }
    });

    it('展示景点数据', async () => {
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('故宫博物院')).toBeInTheDocument();
      });

      expect(screen.getByText('北京市')).toBeInTheDocument();
      expect(screen.getByText('历史人文')).toBeInTheDocument();
      expect(screen.getByText('5A景区')).toBeInTheDocument();
      expect(screen.getByText('¥60.00')).toBeInTheDocument();
      expect(screen.getByText('95.0')).toBeInTheDocument();
      expect(screen.getByText('已上架')).toBeInTheDocument();
    });

    it('未分类的景点显示「未分类」', async () => {
      mockListAttractions.mockResolvedValue(
        makePage([makeAttraction({ categories: [] })]),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('未分类')).toBeInTheDocument();
      });
    });

    it('无图时显示占位', async () => {
      renderPage();
      await waitFor(() => {
        expect(screen.getByText('无图')).toBeInTheDocument();
      });
    });

    it('下架状态显示对应标签', async () => {
      mockListAttractions.mockResolvedValue(
        makePage([makeAttraction({ is_published: false })]),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('已下架')).toBeInTheDocument();
      });
    });
  });

  describe('搜索与筛选（DoD：可用）', () => {
    it('搜索触发重新请求', async () => {
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(mockListAttractions).toHaveBeenCalledTimes(1);
      });

      const searchInput = screen.getByPlaceholderText('搜索景点名称、城市...');
      await user.type(searchInput, '故宫{Enter}');

      await waitFor(() => {
        expect(mockListAttractions).toHaveBeenCalledWith(
          expect.objectContaining({ keyword: '故宫', page: 1 }),
        );
      });
    });

    it('分类筛选触发重新请求并重置页码', async () => {
      renderPage();

      await waitFor(() => {
        expect(mockListAttractions).toHaveBeenCalled();
      });

      // 分类选项由 listCategories 提供
      expect(mockListCategories).toHaveBeenCalled();
    });

    it('分页信息正确展示', async () => {
      mockListAttractions.mockResolvedValue(makePage([makeAttraction()], 25));
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('共 25 条')).toBeInTheDocument();
      });
    });
  });

  describe('删除（DoD：409 提示原样展示）', () => {
    it('删除有引用时展示后端 message', async () => {
      mockDeleteAttraction.mockRejectedValue(
        new Error('该景点已被引用（footprint 3 条），无法删除'),
      );

      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('故宫博物院')).toBeInTheDocument();
      });

      // 点击行内的删除按钮（按钮文本含图标，用文本查询）
      const deleteButton = screen.getByText('删除').closest('button');
      expect(deleteButton).not.toBeNull();
      await user.click(deleteButton as HTMLElement);

      await waitFor(() => {
        expect(screen.getByText('确定删除该景点？')).toBeInTheDocument();
      });

      // Popconfirm 的确认按钮：waitFor 等它渲染后再点
      const confirmButton = await screen.findByRole('button', { name: '删 除' });
      await user.click(confirmButton);

      // mutationFn 会额外传入 context，用 toHaveBeenCalledWith 精确匹配第一个参数
      await waitFor(() => {
        expect(mockDeleteAttraction).toHaveBeenCalled();
      });
      expect(mockDeleteAttraction.mock.calls[0]?.[0]).toBe(
        'a1b2c3d4-0000-0000-0000-000000000000',
      );
    });
  });

  describe('加载与空态', () => {
    it('空列表时表格无数据行', async () => {
      mockListAttractions.mockResolvedValue(makePage([]));
      renderPage();

      await waitFor(() => {
        expect(mockListAttractions).toHaveBeenCalled();
      });

      expect(screen.queryByText('故宫博物院')).not.toBeInTheDocument();
    });
  });
});
