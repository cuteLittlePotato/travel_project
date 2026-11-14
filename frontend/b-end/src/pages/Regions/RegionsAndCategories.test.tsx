/**
 * 省市与分类管理页的组件测试（M11-T14 DoD）。
 *
 * DoD：
 *   - 省市层级正确展示（省份展开显示城市）
 *   - 分类按 theme/level 分组展示
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';

import RegionsPage from './index';
import CategoriesPage from '@/pages/Categories';
import type { PageData } from '@/types/api';
import type { Category, CityListItem, ProvinceListItem } from '@/services/catalog';

const mockListProvinces = vi.fn();
const mockListCities = vi.fn();
const mockListCategories = vi.fn();

vi.mock('@/services/catalog', async () => {
  const actual = await vi.importActual<typeof import('@/services/catalog')>(
    '@/services/catalog',
  );
  return {
    ...actual,
    listProvinces: (...args: unknown[]) => mockListProvinces(...args),
    listCities: (...args: unknown[]) => mockListCities(...args),
    listCategories: (...args: unknown[]) => mockListCategories(...args),
    deleteProvince: vi.fn(),
    deleteCity: vi.fn(),
    deleteCategory: vi.fn(),
    createProvince: vi.fn(),
    updateProvince: vi.fn(),
    createCity: vi.fn(),
    updateCity: vi.fn(),
    createCategory: vi.fn(),
    updateCategory: vi.fn(),
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

const ZHEJIANG: ProvinceListItem = {
  id: 'p-zj',
  parent_id: null,
  name: '浙江省',
  level: 1,
  code: '330000',
  description: null,
  cover_image_url: null,
  heat_score: '88.50',
  sort_weight: 100,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  city_count: 2,
};

const JIANGSU: ProvinceListItem = {
  ...ZHEJIANG,
  id: 'p-js',
  name: '江苏省',
  code: '320000',
  heat_score: '80.00',
  city_count: 0,
};

function makeCity(overrides: Partial<CityListItem> = {}): CityListItem {
  return {
    id: 'c-hz',
    parent_id: 'p-zj',
    name: '杭州市',
    level: 2,
    code: '330100',
    description: null,
    cover_image_url: null,
    heat_score: '95.00',
    sort_weight: 100,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    province_name: '浙江省',
    attraction_count: 12,
    ...overrides,
  };
}

function makeCategory(overrides: Partial<Category> = {}): Category {
  return {
    id: 'cat-1',
    name: '历史人文',
    category_type: 'theme',
    parent_id: null,
    description: '古迹、博物馆等',
    sort_weight: 100,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    attraction_count: 45,
    ...overrides,
  };
}

describe('RegionsPage（DoD：省市层级展示）', () => {
  beforeEach(() => {
    mockListProvinces.mockReset();
    mockListCities.mockReset();
    mockListProvinces.mockResolvedValue({ items: [ZHEJIANG, JIANGSU] });
    mockListCities.mockResolvedValue(makePage([makeCity()]));
  });

  it('列出省份并显示城市数', async () => {
    renderWithProviders(<RegionsPage />);

    await waitFor(() => {
      expect(screen.getByText('浙江省')).toBeInTheDocument();
    });

    expect(screen.getByText('江苏省')).toBeInTheDocument();
    expect(screen.getByText('330000')).toBeInTheDocument();
    // 浙江省有 2 个城市
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('表头符合设计', async () => {
    renderWithProviders(<RegionsPage />);

    await waitFor(() => {
      expect(screen.getByText('浙江省')).toBeInTheDocument();
    });

    for (const header of [
      '省份名称', '行政区划编码', '热度', '城市数', '排序', '操作',
    ]) {
      expect(screen.getByRole('columnheader', { name: header })).toBeInTheDocument();
    }
  });

  it('展开省份行后按 province_id 拉取该省城市', async () => {
    const user = userEvent.setup();
    renderWithProviders(<RegionsPage />);

    await waitFor(() => {
      expect(screen.getByText('浙江省')).toBeInTheDocument();
    });

    // 展开按钮在每行首列
    const expandButton = screen.getAllByRole('button', {
      name: /展开行|Expand row/i,
    })[0];
    expect(expandButton).toBeDefined();
    await user.click(expandButton as HTMLElement);

    await waitFor(() => {
      expect(screen.getByText('杭州市')).toBeInTheDocument();
    });

    // DoD：城市查询必须带省份过滤，否则会把所有城市都列出来
    expect(mockListCities).toHaveBeenCalledWith(
      expect.objectContaining({ province_id: 'p-zj' }),
    );
  });

  it('城市子表展示省份归属的景点数', async () => {
    const user = userEvent.setup();
    renderWithProviders(<RegionsPage />);

    await waitFor(() => {
      expect(screen.getByText('浙江省')).toBeInTheDocument();
    });

    const expandButton = screen.getAllByRole('button', {
      name: /展开行|Expand row/i,
    })[0];
    expect(expandButton).toBeDefined();
    await user.click(expandButton as HTMLElement);

    await waitFor(() => {
      expect(screen.getByText('杭州市')).toBeInTheDocument();
    });

    expect(screen.getByText('330100')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
  });

  it('省份删除前提示下级城市数（DoD：删除引用提示）', async () => {
    const user = userEvent.setup();
    renderWithProviders(<RegionsPage />);

    await waitFor(() => {
      expect(screen.getByText('浙江省')).toBeInTheDocument();
    });

    const row = screen.getByText('浙江省').closest('tr');
    expect(row).not.toBeNull();

    const deleteButton = within(row as HTMLElement)
      .getByText('删除')
      .closest('button');
    await user.click(deleteButton as HTMLButtonElement);

    await waitFor(() => {
      expect(screen.getByText(/还有 2 个城市，删除会被拒绝/)).toBeInTheDocument();
    });
  });

  it('搜索框按关键词过滤', async () => {
    const user = userEvent.setup();
    renderWithProviders(<RegionsPage />);

    await waitFor(() => {
      expect(screen.getByText('浙江省')).toBeInTheDocument();
    });

    await user.type(screen.getByPlaceholderText('搜索省份名称'), '浙江{enter}');

    await waitFor(() => {
      expect(mockListProvinces).toHaveBeenCalledWith('浙江');
    });
  });
});

/** 取当前激活的 Tab 面板（非激活面板不带 tabpanel 角色） */
function getActiveTabPanel(): HTMLElement {
  return screen.getByRole('tabpanel');
}

describe('CategoriesPage（DoD：按 theme/level 分组）', () => {
  const THEME = makeCategory();
  const LEVEL = makeCategory({
    id: 'cat-5a',
    name: '5A 景区',
    category_type: 'level',
    description: '国家 5A 级旅游景区',
    attraction_count: 8,
  });

  beforeEach(() => {
    mockListCategories.mockReset();
    mockListCategories.mockResolvedValue({ items: [THEME, LEVEL] });
  });

  it('两个 Tab 分别显示各自数量', async () => {
    renderWithProviders(<CategoriesPage />);

    // 数量来自接口，需等数据返回后 Tab 标题才会更新
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /主题分类（1）/ })).toBeInTheDocument();
    });

    expect(screen.getByRole('tab', { name: /等级分类（1）/ })).toBeInTheDocument();
  });

  it('主题 Tab 只显示 theme 分类，不串入 level', async () => {
    renderWithProviders(<CategoriesPage />);

    await waitFor(() => {
      expect(getActiveTabPanel()).toHaveTextContent('历史人文');
    });

    expect(getActiveTabPanel()).not.toHaveTextContent('5A 景区');
  });

  it('切到等级 Tab 显示 level 分类', async () => {
    const user = userEvent.setup();
    renderWithProviders(<CategoriesPage />);

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /等级分类/ })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('tab', { name: /等级分类/ }));

    // antd Tabs 默认保留非激活面板（仅隐藏），因此按「激活面板内容」断言分组正确
    await waitFor(() => {
      expect(getActiveTabPanel()).toHaveTextContent('5A 景区');
    });
    expect(getActiveTabPanel()).not.toHaveTextContent('历史人文');
  });

  it('展示分类的景点数', async () => {
    renderWithProviders(<CategoriesPage />);

    await waitFor(() => {
      expect(screen.getByText('历史人文')).toBeInTheDocument();
    });

    expect(screen.getByText('45')).toBeInTheDocument();
  });

  it('分类表头符合设计', async () => {
    renderWithProviders(<CategoriesPage />);

    await waitFor(() => {
      expect(screen.getByText('历史人文')).toBeInTheDocument();
    });

    for (const header of ['分类名称', '描述', '景点数', '排序', '操作']) {
      expect(screen.getByRole('columnheader', { name: header })).toBeInTheDocument();
    }
  });

  it('有景点关联的分类删除时给出引用提示', async () => {
    const user = userEvent.setup();
    renderWithProviders(<CategoriesPage />);

    await waitFor(() => {
      expect(screen.getByText('历史人文')).toBeInTheDocument();
    });

    const row = screen.getByText('历史人文').closest('tr');
    expect(row).not.toBeNull();

    const deleteButton = within(row as HTMLElement)
      .getByText('删除')
      .closest('button');
    await user.click(deleteButton as HTMLButtonElement);

    await waitFor(() => {
      expect(screen.getByText(/已有 45 个景点使用此分类/)).toBeInTheDocument();
    });
  });

  it('空分类列表时 Tab 数量为 0', async () => {
    mockListCategories.mockResolvedValue({ items: [] });
    renderWithProviders(<CategoriesPage />);

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /主题分类（0）/ })).toBeInTheDocument();
    });
    expect(screen.getByRole('tab', { name: /等级分类（0）/ })).toBeInTheDocument();
  });
});
