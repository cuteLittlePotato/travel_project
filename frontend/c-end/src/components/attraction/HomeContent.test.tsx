/**
 * 首页相关组件的测试（M02-T09 DoD）。
 *
 * DoD：
 *   - 服务端渲染首屏包含景点卡片（由 build 输出的静态页面验证）
 *   - 分类与省市筛选联动（集成测试）
 *   - 热度值 hover 显示 recommend_reason（组件测试）
 *   - 与原型 home.html 的信息结构一致
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { AttractionCard } from './AttractionCard';
import { HomeContent } from './HomeContent';
import type {
  AttractionList,
  AttractionListItem,
  CategoryGrouped,
  RegionBrief,
} from '@/services/attraction';

const mockGet = vi.fn();

vi.mock('@/lib/api/http', () => ({
  http: {
    get: (...args: unknown[]) => mockGet(...args),
  },
}));

function makeAttraction(overrides: Partial<AttractionListItem> = {}): AttractionListItem {
  return {
    id: 'a1',
    name: '故宫博物院',
    city: { id: 'c1', name: '北京市', code: '110100', level: 2, heat_score: '0' },
    categories: [{ id: 'cat1', name: '历史人文', category_type: 'theme', sort_weight: 0 }],
    summary: '中国明清两代的皇家宫殿',
    image_url: null,
    ticket_price: '60.00',
    popularity: 95,
    recommend_reason: null,
    ...overrides,
  };
}

function makeList(items: AttractionListItem[]): AttractionList {
  return { items, total: items.length, page: 1, page_size: 12, total_pages: 1 };
}

const CATEGORIES: CategoryGrouped = {
  themes: [{ id: 'cat1', name: '历史人文', category_type: 'theme', sort_weight: 100 }],
  levels: [{ id: 'cat2', name: '5A景区', category_type: 'level', sort_weight: 100 }],
};

const PROVINCES: RegionBrief[] = [
  { id: 'p1', name: '北京市', code: '110000', level: 1, heat_score: '0' },
  { id: 'p2', name: '浙江省', code: '330000', level: 1, heat_score: '0' },
];

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe('AttractionCard', () => {
  it('展示名称、城市、分类、价格、热度', () => {
    renderWithProviders(<AttractionCard attraction={makeAttraction()} />);

    expect(screen.getByText('故宫博物院')).toBeInTheDocument();
    expect(screen.getByText(/北京市/)).toBeInTheDocument();
    expect(screen.getByText(/历史人文/)).toBeInTheDocument();
    expect(screen.getByText('¥60')).toBeInTheDocument();
    expect(screen.getByText(/95\.0/)).toBeInTheDocument();
  });

  it('链接指向详情页', () => {
    renderWithProviders(<AttractionCard attraction={makeAttraction()} />);

    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', '/attraction/a1');
  });

  it('免费景点显示「免费」', () => {
    renderWithProviders(
      <AttractionCard attraction={makeAttraction({ ticket_price: null })} />,
    );
    expect(screen.getByText('免费')).toBeInTheDocument();
  });

  it('**无图片时降级为渐变背景**（含景点名前两字）', () => {
    renderWithProviders(
      <AttractionCard attraction={makeAttraction({ image_url: null })} />,
    );
    // 图片区显示名字前两字作为占位
    expect(screen.getByText('故宫')).toBeInTheDocument();
  });

  it('有图片时渲染 img', () => {
    const { container } = renderWithProviders(
      <AttractionCard
        attraction={makeAttraction({ image_url: 'https://example.com/a.jpg' })}
      />,
    );
    expect(container.querySelector('img')).toHaveAttribute(
      'src',
      'https://example.com/a.jpg',
    );
  });

  describe('热度 hover（DoD）', () => {
    it('有 recommend_reason 时作为 tooltip 展示', () => {
      renderWithProviders(
        <AttractionCard
          attraction={makeAttraction({ recommend_reason: '热门历史文化景点' })}
        />,
      );

      const popularity = screen.getByTitle('热门历史文化景点');
      expect(popularity).toBeInTheDocument();
      expect(popularity).toHaveStyle({ cursor: 'help' });
    });

    it('无 recommend_reason 时无 tooltip', () => {
      renderWithProviders(
        <AttractionCard attraction={makeAttraction({ recommend_reason: null })} />,
      );

      // 热度元素存在但无 title
      const popularity = screen.getByText(/95\.0/);
      expect(popularity).not.toHaveAttribute('title');
    });
  });

  it('排行榜徽章显示名次', () => {
    renderWithProviders(<AttractionCard attraction={makeAttraction()} showRank={1} />);
    expect(screen.getByText('1')).toBeInTheDocument();
  });
});

describe('HomeContent', () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  const INITIAL = makeList([makeAttraction()]);

  it('渲染首屏服务端数据', () => {
    renderWithProviders(
      <HomeContent
        initialAttractions={INITIAL}
        categories={CATEGORIES}
        provinces={PROVINCES}
      />,
    );

    expect(screen.getByText('故宫博物院')).toBeInTheDocument();
    expect(screen.getByText('🔥 热度排行')).toBeInTheDocument();
  });

  it('**首屏不重复请求**（用服务端数据）', () => {
    renderWithProviders(
      <HomeContent
        initialAttractions={INITIAL}
        categories={CATEGORIES}
        provinces={PROVINCES}
      />,
    );

    // 没有筛选条件时不应发起请求
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('信息结构包含原型的关键区块', () => {
    renderWithProviders(
      <HomeContent
        initialAttractions={INITIAL}
        categories={CATEGORIES}
        provinces={PROVINCES}
      />,
    );

    expect(screen.getByText('发现你的下一个旅行目的地')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/搜索景点/)).toBeInTheDocument();
    expect(screen.getByText('热度排行', { exact: false })).toBeInTheDocument();
  });

  it('渲染分类标签', () => {
    renderWithProviders(
      <HomeContent
        initialAttractions={INITIAL}
        categories={CATEGORIES}
        provinces={PROVINCES}
      />,
    );

    expect(screen.getByText('全部')).toBeInTheDocument();
    expect(screen.getByText('历史人文')).toBeInTheDocument();
    expect(screen.getByText('5A景区')).toBeInTheDocument();
  });

  it('渲染省份下拉', () => {
    renderWithProviders(
      <HomeContent
        initialAttractions={INITIAL}
        categories={CATEGORIES}
        provinces={PROVINCES}
      />,
    );

    const provinceSelect = screen.getByLabelText('选择省份');
    expect(provinceSelect).toBeInTheDocument();
    expect(screen.getByText('全部省份')).toBeInTheDocument();
  });

  it('城市下拉在未选省份时禁用', () => {
    renderWithProviders(
      <HomeContent
        initialAttractions={INITIAL}
        categories={CATEGORIES}
        provinces={PROVINCES}
      />,
    );

    const citySelect = screen.getByLabelText('选择城市');
    expect(citySelect).toBeDisabled();
  });

  describe('筛选联动（DoD）', () => {
    it('点击分类后发起筛选请求', async () => {
      mockGet.mockResolvedValue({
        data: { code: 0, message: 'ok', data: makeList([]) },
      });
      const user = userEvent.setup();

      renderWithProviders(
        <HomeContent
          initialAttractions={INITIAL}
          categories={CATEGORIES}
          provinces={PROVINCES}
        />,
      );

      await user.click(screen.getByText('历史人文'));

      await waitFor(() => {
        expect(mockGet).toHaveBeenCalled();
      });

      const url = mockGet.mock.calls[0]?.[0] as string;
      expect(url).toContain('category_ids=cat1');
    });

    it('筛选无结果时展示空状态', async () => {
      mockGet.mockResolvedValue({
        data: { code: 0, message: 'ok', data: makeList([]) },
      });
      const user = userEvent.setup();

      renderWithProviders(
        <HomeContent
          initialAttractions={INITIAL}
          categories={CATEGORIES}
          provinces={PROVINCES}
        />,
      );

      await user.click(screen.getByText('历史人文'));

      await waitFor(() => {
        expect(screen.getByText('没有符合条件的景点')).toBeInTheDocument();
      });
    });

    it('选择省份后城市下拉可用', async () => {
      mockGet.mockResolvedValue({
        data: { code: 0, message: 'ok', data: { items: [] } },
      });
      const user = userEvent.setup();

      renderWithProviders(
        <HomeContent
          initialAttractions={INITIAL}
          categories={CATEGORIES}
          provinces={PROVINCES}
        />,
      );

      await user.selectOptions(screen.getByLabelText('选择省份'), 'p1');

      await waitFor(() => {
        expect(screen.getByLabelText('选择城市')).not.toBeDisabled();
      });
    });

    it('**切换省份时清空已选城市**', async () => {
      mockGet.mockResolvedValue({
        data: { code: 0, message: 'ok', data: { items: [] } },
      });
      const user = userEvent.setup();

      renderWithProviders(
        <HomeContent
          initialAttractions={INITIAL}
          categories={CATEGORIES}
          provinces={PROVINCES}
        />,
      );

      const citySelect = screen.getByLabelText('选择城市') as HTMLSelectElement;

      await user.selectOptions(screen.getByLabelText('选择省份'), 'p1');
      // 此时城市下拉已有选项（mock 返回空，但选中值可设）
      await waitFor(() => {
        expect(citySelect).not.toBeDisabled();
      });

      // 换省份
      await user.selectOptions(screen.getByLabelText('选择省份'), 'p2');

      // 城市应被清空，否则会残留上一个省的城市导致结果为空
      expect(citySelect.value).toBe('');
    });
  });

  describe('搜索', () => {
    it('回车触发搜索', async () => {
      mockGet.mockResolvedValue({
        data: { code: 0, message: 'ok', data: makeList([]) },
      });
      const user = userEvent.setup();

      renderWithProviders(
        <HomeContent
          initialAttractions={INITIAL}
          categories={CATEGORIES}
          provinces={PROVINCES}
        />,
      );

      await user.type(screen.getByPlaceholderText(/搜索景点/), '故宫{enter}');

      await waitFor(() => {
        expect(mockGet).toHaveBeenCalled();
      });
      expect((mockGet.mock.calls[0]?.[0] as string)).toContain('keyword=');
    });

    it('点搜索按钮触发搜索', async () => {
      mockGet.mockResolvedValue({
        data: { code: 0, message: 'ok', data: makeList([]) },
      });
      const user = userEvent.setup();

      renderWithProviders(
        <HomeContent
          initialAttractions={INITIAL}
          categories={CATEGORIES}
          provinces={PROVINCES}
        />,
      );

      await user.type(screen.getByPlaceholderText(/搜索景点/), '西湖');
      await user.click(screen.getByRole('button', { name: '搜索' }));

      await waitFor(() => {
        expect(mockGet).toHaveBeenCalled();
      });
    });
  });
});
