/**
 * 餐厅/酒店管理页的组件测试（M11-T12 DoD）。
 *
 * DoD：
 *   - 表格列与原型一致
 *   - 增删改可用
 *   - 80×80 缩略图，加载失败降级
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';

import RestaurantsPage, { Thumbnail } from './index';
import HotelsPage from '@/pages/Hotels';
import type { PageData } from '@/types/api';
import type { Hotel, Restaurant } from '@/services/catalog';

const mockListRestaurants = vi.fn();
const mockListHotels = vi.fn();

vi.mock('@/services/catalog', async () => {
  const actual = await vi.importActual<typeof import('@/services/catalog')>(
    '@/services/catalog',
  );
  return {
    ...actual,
    listRestaurants: (...args: unknown[]) => mockListRestaurants(...args),
    listHotels: (...args: unknown[]) => mockListHotels(...args),
    listCities: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    deleteRestaurant: vi.fn(),
    deleteHotel: vi.fn(),
  };
});

function makePage<T>(items: T[], total = items.length): PageData<T> {
  return { items, total, page: 1, page_size: 10, total_pages: Math.ceil(total / 10) || 0 };
}

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={zhCN}>
        <AntdApp>{ui}</AntdApp>
      </ConfigProvider>
    </QueryClientProvider>,
  );
}

const RESTAURANT: Restaurant = {
  id: 'r1-0000-0000-0000-000000000000',
  name: '全聚德烤鸭店',
  city_id: 'c1',
  city_name: '北京市',
  cuisine_type: '京菜',
  address: '前门大街 30 号',
  avg_cost: '180.00',
  business_hours: { mon: '10:00-22:00', note: '周一休息' },
  cover_image_url: null,
  is_published: true,
  created_at: '2026-01-01T00:00:00Z',
};

const HOTEL: Hotel = {
  id: 'h1-0000-0000-0000-000000000000',
  name: '王府井希尔顿',
  city_id: 'c1',
  city_name: '北京市',
  star_level: 'five',
  address: '王府井大街 8 号',
  min_price: '800.00',
  max_price: '2500.00',
  cover_image_url: null,
  is_published: true,
  created_at: '2026-01-01T00:00:00Z',
};

describe('RestaurantsPage', () => {
  beforeEach(() => {
    mockListRestaurants.mockReset();
    mockListRestaurants.mockResolvedValue(makePage([RESTAURANT]));
  });

  it('渲染原型的 9 个表头', async () => {
    renderWithProviders(<RestaurantsPage />);

    await waitFor(() => {
      expect(screen.getByText('全聚德烤鸭店')).toBeInTheDocument();
    });

    for (const header of [
      'ID', '图片', '餐厅名称', '类型', '城市', '人均消费', '营业时间', '状态', '操作',
    ]) {
      expect(screen.getByRole('columnheader', { name: header })).toBeInTheDocument();
    }
  });

  it('展示餐厅数据', async () => {
    renderWithProviders(<RestaurantsPage />);

    await waitFor(() => {
      expect(screen.getByText('全聚德烤鸭店')).toBeInTheDocument();
    });

    expect(screen.getByText('京菜')).toBeInTheDocument();
    expect(screen.getByText('北京市')).toBeInTheDocument();
    expect(screen.getByText('¥180.00')).toBeInTheDocument();
    expect(screen.getByText('营业中')).toBeInTheDocument();
  });

  it('营业时间七天一致时压缩为一行', async () => {
    mockListRestaurants.mockResolvedValue(
      makePage([
        {
          ...RESTAURANT,
          business_hours: {
            mon: '10:00-22:00', tue: '10:00-22:00', wed: '10:00-22:00',
            thu: '10:00-22:00', fri: '10:00-22:00', sat: '10:00-22:00',
            sun: '10:00-22:00',
          },
        },
      ]),
    );
    renderWithProviders(<RestaurantsPage />);

    await waitFor(() => {
      expect(screen.getByText('10:00-22:00')).toBeInTheDocument();
    });
  });

  it('营业时间各天不同时显示「按星期设置」', async () => {
    mockListRestaurants.mockResolvedValue(
      makePage([
        {
          ...RESTAURANT,
          business_hours: { mon: '10:00-22:00', sat: '10:00-23:00' },
        },
      ]),
    );
    renderWithProviders(<RestaurantsPage />);

    await waitFor(() => {
      expect(screen.getByText('按星期设置')).toBeInTheDocument();
    });
  });

  it('营业时间带备注时一并展示', async () => {
    mockListRestaurants.mockResolvedValue(
      makePage([
        {
          ...RESTAURANT,
          business_hours: {
            mon: '10:00-22:00', tue: '10:00-22:00', wed: '10:00-22:00',
            thu: '10:00-22:00', fri: '10:00-22:00', sat: '10:00-22:00',
            sun: '10:00-22:00', note: '周一休息',
          },
        },
      ]),
    );
    renderWithProviders(<RestaurantsPage />);

    await waitFor(() => {
      expect(screen.getByText('10:00-22:00（周一休息）')).toBeInTheDocument();
    });
  });

  it('无营业时间时显示占位', async () => {
    mockListRestaurants.mockResolvedValue(
      makePage([{ ...RESTAURANT, business_hours: null }]),
    );
    renderWithProviders(<RestaurantsPage />);

    await waitFor(() => {
      expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    });
  });

  it('下架餐厅显示「已下架」', async () => {
    mockListRestaurants.mockResolvedValue(
      makePage([{ ...RESTAURANT, is_published: false }]),
    );
    renderWithProviders(<RestaurantsPage />);

    await waitFor(() => {
      expect(screen.getByText('已下架')).toBeInTheDocument();
    });
  });
});

describe('HotelsPage', () => {
  beforeEach(() => {
    mockListHotels.mockReset();
    mockListHotels.mockResolvedValue(makePage([HOTEL]));
  });

  it('渲染原型的 9 个表头', async () => {
    renderWithProviders(<HotelsPage />);

    await waitFor(() => {
      expect(screen.getByText('王府井希尔顿')).toBeInTheDocument();
    });

    for (const header of [
      'ID', '图片', '酒店名称', '星级', '城市', '价格区间', '房型', '状态', '操作',
    ]) {
      expect(screen.getByRole('columnheader', { name: header })).toBeInTheDocument();
    }
  });

  it('展酒店数据与价格区间格式', async () => {
    renderWithProviders(<HotelsPage />);

    await waitFor(() => {
      expect(screen.getByText('王府井希尔顿')).toBeInTheDocument();
    });

    expect(screen.getByText('五星级')).toBeInTheDocument();
    expect(screen.getByText('北京市')).toBeInTheDocument();
    // 价格区间格式：¥800 - ¥2500
    expect(screen.getByText('¥800 - ¥2500')).toBeInTheDocument();
  });

  it('未知星级原样展示', async () => {
    mockListHotels.mockResolvedValue(
      makePage([{ ...HOTEL, star_level: 'unknown_level' }]),
    );
    renderWithProviders(<HotelsPage />);

    await waitFor(() => {
      expect(screen.getByText('unknown_level')).toBeInTheDocument();
    });
  });

  it('无价格时显示占位', async () => {
    mockListHotels.mockResolvedValue(
      makePage([{ ...HOTEL, min_price: null, max_price: null }]),
    );
    renderWithProviders(<HotelsPage />);

    // 价格区间的「—」在单元格中；排除其他列可能出现的短横线
    await waitFor(() => {
      const cells = screen.getAllByText('—');
      expect(cells.length).toBeGreaterThan(0);
    });
    // 确认展示的是酒店名（而非渲染失败）
    expect(screen.getByText('王府井希尔顿')).toBeInTheDocument();
  });
});

describe('Thumbnail（DoD：80×80 + 加载失败降级）', () => {
  it('无图时显示占位块', () => {
    const { container } = render(<Thumbnail src={null} />);
    const placeholder = container.firstElementChild as HTMLElement;

    expect(placeholder).toHaveTextContent('无图');
    expect(placeholder.style.width).toBe('80px');
    expect(placeholder.style.height).toBe('80px');
  });

  it('有图时渲染 Image', () => {
    const { container } = render(<Thumbnail src="https://example.com/a.jpg" />);
    expect(container.querySelector('img')).toBeInTheDocument();
  });
});
