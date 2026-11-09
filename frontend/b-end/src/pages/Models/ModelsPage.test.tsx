/**
 * 模型管理页的组件测试（M12-T09 DoD）。
 *
 * DoD：
 *   - 5 个类别标签页带数量角标
 *   - 编辑时类别字段禁用
 *   - 删除时的保护提示正确展示
 *   - 与原型 models.html 布局一致
 * 边界：API Key 展示为密文输入框，不回显原值
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';

import ModelsPage from './index';
import { CATEGORY_META } from './constants';
import type { PageData } from '@/types/api';
import type { Model, ModelCategoryOption } from '@/services/model';

const mockListModels = vi.fn();
const mockListCategories = vi.fn();
const mockSetStatus = vi.fn();
const mockSetDefault = vi.fn();
const mockDeleteModel = vi.fn();
const mockCreateModel = vi.fn();
const mockUpdateModel = vi.fn();

vi.mock('@/services/model', async () => {
  const actual = await vi.importActual<typeof import('@/services/model')>(
    '@/services/model',
  );
  return {
    ...actual,
    listModels: (...args: unknown[]) => mockListModels(...args),
    listModelCategories: (...args: unknown[]) => mockListCategories(...args),
    setModelStatus: (...args: unknown[]) => mockSetStatus(...args),
    setModelDefault: (...args: unknown[]) => mockSetDefault(...args),
    deleteModel: (...args: unknown[]) => mockDeleteModel(...args),
    createModel: (...args: unknown[]) => mockCreateModel(...args),
    updateModel: (...args: unknown[]) => mockUpdateModel(...args),
  };
});

const CATEGORIES: ModelCategoryOption[] = [
  { code: 'chat', name: '文本对话' },
  { code: 'vision', name: '图片理解' },
  { code: 'embedding', name: '向量化' },
  { code: 'rerank', name: '重排序' },
  { code: 'ocr', name: 'OCR解析' },
];

function makeModel(overrides: Partial<Model> = {}): Model {
  return {
    id: 'model-1-0000-0000-000000000000',
    name: 'DeepSeek-V3',
    category: 'chat',
    model_code: 'deepseek-chat',
    base_url: 'https://api.deepseek.com/v1',
    max_context_tokens: 128000,
    max_output_tokens: 4096,
    timeout_seconds: 60,
    concurrency_limit: 20,
    price_input: '0.001',
    price_output: '0.002',
    description: '主用对话模型',
    is_enabled: true,
    is_default: false,
    last_test_at: null,
    last_test_ok: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    has_api_key: true,
    ...overrides,
  };
}

function makePage(items: Model[]): PageData<Model> {
  return {
    items,
    total: items.length,
    page: 1,
    page_size: 100,
    total_pages: 1,
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
          <ModelsPage />
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>,
  );
}

describe('ModelsPage', () => {
  beforeEach(() => {
    mockListModels.mockReset();
    mockListCategories.mockReset();
    mockSetStatus.mockReset();
    mockSetDefault.mockReset();
    mockDeleteModel.mockReset();

    mockListCategories.mockResolvedValue({ items: CATEGORIES });
    mockListModels.mockResolvedValue(
      makePage([
        makeModel(),
        makeModel({
          id: 'model-2',
          name: 'GPT-4V',
          category: 'vision',
          model_code: 'gpt-4-vision',
          is_default: true,
        }),
        makeModel({
          id: 'model-3',
          name: 'text-embedding-3',
          category: 'embedding',
          model_code: 'text-embedding-3-large',
          max_context_tokens: null,
        }),
      ]),
    );
  });

  describe('类别标签页（DoD 1）', () => {
    it('渲染全部 + 5 个类别标签', async () => {
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('全部 (3)')).toBeInTheDocument();
      });

      // 断言每个类别的标签都在（数量已在下一个用例精确断言）
      for (const category of CATEGORIES) {
        const label = screen
          .getAllByText(new RegExp(category.name))
          .find((el) => /\(\d+\)/.test(el.textContent ?? ''));
        expect(label, `缺少类别标签：${category.name}`).toBeDefined();
      }
    });

    it('每个标签带数量角标', async () => {
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('全部 (3)')).toBeInTheDocument();
      });

      // chat/vision/embedding 各 1，rerank/ocr 为 0
      expect(screen.getByText('文本对话 (1)')).toBeInTheDocument();
      expect(screen.getByText('图片理解 (1)')).toBeInTheDocument();
      expect(screen.getByText('向量化 (1)')).toBeInTheDocument();
      expect(screen.getByText('重排序 (0)')).toBeInTheDocument();
      expect(screen.getByText('OCR解析 (0)')).toBeInTheDocument();
    });

    it('数量之和等于全部', async () => {
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('全部 (3)')).toBeInTheDocument();
      });

      const counts = [1, 1, 1, 0, 0];
      expect(counts.reduce((a, b) => a + b, 0)).toBe(3);
    });

    it('切换到某类别后只显示该类模型', async () => {
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('DeepSeek-V3')).toBeInTheDocument();
      });

      await user.click(screen.getByText('文本对话 (1)'));

      await waitFor(() => {
        expect(screen.getByText('DeepSeek-V3')).toBeInTheDocument();
      });
      expect(screen.queryByText('GPT-4V')).not.toBeInTheDocument();
    });
  });

  describe('模型卡片（DoD 4：与原型布局一致）', () => {
    it('展示名称与调用模型 ID', async () => {
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('DeepSeek-V3')).toBeInTheDocument();
      });
      expect(screen.getByText('deepseek-chat')).toBeInTheDocument();
    });

    it('每个类别有对应图标', () => {
      expect(CATEGORY_META.chat.icon).toBe('💬');
      expect(CATEGORY_META.vision.icon).toBe('🖼️');
      expect(CATEGORY_META.embedding.icon).toBe('🔢');
      expect(CATEGORY_META.rerank.icon).toBe('📊');
      expect(CATEGORY_META.ocr.icon).toBe('📄');
    });

    it('默认模型显示「默认」徽章', async () => {
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('GPT-4V')).toBeInTheDocument();
      });
      expect(screen.getByText('默认')).toBeInTheDocument();
    });

    it('展示启用状态', async () => {
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('DeepSeek-V3')).toBeInTheDocument();
      });

      expect(screen.getAllByText('已启用').length).toBeGreaterThan(0);
    });

    it('展示接口地址', async () => {
      renderPage();

      await waitFor(() => {
        expect(
          screen.getAllByText('https://api.deepseek.com/v1').length,
        ).toBeGreaterThan(0);
      });
    });

    it('展示上下文长度', async () => {
      renderPage();

      // 千分位格式随 locale 变化，且文本被拆成两个节点，
      // 因此用函数匹配器检查父节点的完整文本
      await waitFor(() => {
        const found = screen.getAllByText((_, node) => {
          const text = node?.textContent ?? '';
          return node?.tagName === 'SPAN' && /128[,，]?000 tokens/.test(text);
        });
        expect(found.length).toBeGreaterThan(0);
      });
    });

    it('无上下文的类别不显示该行', async () => {
      mockListModels.mockResolvedValue(
        makePage([makeModel({ max_context_tokens: null })]),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('DeepSeek-V3')).toBeInTheDocument();
      });
      expect(screen.queryByText(/tokens$/)).not.toBeInTheDocument();
    });
  });

  describe('API Key 展示（边界：不回显原值）', () => {
    it('已配置时显示「已配置」而非密钥内容', async () => {
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('DeepSeek-V3')).toBeInTheDocument();
      });
      expect(screen.getAllByText('已配置').length).toBeGreaterThan(0);
    });

    it('未配置时显示「未配置」', async () => {
      mockListModels.mockResolvedValue(
        makePage([makeModel({ has_api_key: false })]),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('未配置')).toBeInTheDocument();
      });
    });

    it('页面中不出现 sk- 开头的密钥文本', async () => {
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('DeepSeek-V3')).toBeInTheDocument();
      });
      expect(document.body.textContent).not.toMatch(/sk-[a-zA-Z0-9]{10,}/);
    });
  });

  describe('编辑时类别禁用（DoD 2）', () => {
    it('编辑模态框中类别 Select 被禁用', async () => {
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('DeepSeek-V3')).toBeInTheDocument();
      });

      const card = screen.getByText('DeepSeek-V3').closest('.ant-card');
      expect(card).not.toBeNull();

      await user.click(
        within(card as HTMLElement).getByText('编辑').closest('button')!,
      );

      await waitFor(() => {
        expect(screen.getByText('编辑模型')).toBeInTheDocument();
      });

      // 类别选择器禁用
      const categorySelect = screen.getByText('模型类别')
        .closest('.ant-form-item')!
        .querySelector('.ant-select');
      expect(categorySelect?.className).toContain('ant-select-disabled');

      // 提示文案
      expect(screen.getByText('类别注册后不可修改')).toBeInTheDocument();
    });

    it('编辑时 API Key 输入框为空且提示「保持原值」', async () => {
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('DeepSeek-V3')).toBeInTheDocument();
      });

      const card = screen.getByText('DeepSeek-V3').closest('.ant-card');
      await user.click(
        within(card as HTMLElement).getByText('编辑').closest('button')!,
      );

      await waitFor(() => {
        expect(screen.getByText('留空表示保持原值；填写则覆盖')).toBeInTheDocument();
      });

      const passwordInput = document.querySelector(
        'input[type="password"]',
      ) as HTMLInputElement | null;
      expect(passwordInput).not.toBeNull();
      expect(passwordInput?.value).toBe('');
    });
  });

  describe('删除保护提示（DoD 3）', () => {
    it('默认模型的删除提示说明不能删', async () => {
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('GPT-4V')).toBeInTheDocument();
      });

      const card = screen.getByText('GPT-4V').closest('.ant-card');
      await user.click(
        within(card as HTMLElement).getByText('删除').closest('button')!,
      );

      await waitFor(() => {
        expect(
          screen.getByText('默认模型不能删除，请先更换默认'),
        ).toBeInTheDocument();
      });
    });

    it('普通模型的删除提示说明日志保留', async () => {
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('DeepSeek-V3')).toBeInTheDocument();
      });

      const card = screen.getByText('DeepSeek-V3').closest('.ant-card');
      await user.click(
        within(card as HTMLElement).getByText('删除').closest('button')!,
      );

      await waitFor(() => {
        expect(screen.getByText('删除后历史调用日志保留')).toBeInTheDocument();
      });
    });
  });

  describe('操作行为', () => {
    it('默认模型的启用开关被禁用', async () => {
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('GPT-4V')).toBeInTheDocument();
      });

      const card = screen.getByText('GPT-4V').closest('.ant-card');
      const switchEl = within(card as HTMLElement).getByRole('switch');

      expect(switchEl).toBeDisabled();
    });

    it('未启用模型不能设默认（按钮禁用）', async () => {
      mockListModels.mockResolvedValue(
        makePage([makeModel({ is_enabled: false, is_default: false })]),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('DeepSeek-V3')).toBeInTheDocument();
      });

      const button = screen.getByText('设默认').closest('button');
      expect(button).toBeDisabled();
    });

    it('已是默认的模型设默认按钮禁用', async () => {
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('GPT-4V')).toBeInTheDocument();
      });

      const card = screen.getByText('GPT-4V').closest('.ant-card');
      const button = within(card as HTMLElement)
        .getByText('设默认')
        .closest('button');
      expect(button).toBeDisabled();
    });
  });

  describe('搜索与空态', () => {
    it('按名称搜索过滤', async () => {
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('DeepSeek-V3')).toBeInTheDocument();
      });

      await user.type(screen.getByPlaceholderText('搜索模型名称...'), 'GPT');

      await waitFor(() => {
        expect(screen.queryByText('DeepSeek-V3')).not.toBeInTheDocument();
      });
      expect(screen.getByText('GPT-4V')).toBeInTheDocument();
    });

    it('按 model_code 搜索过滤', async () => {
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('DeepSeek-V3')).toBeInTheDocument();
      });

      await user.type(
        screen.getByPlaceholderText('搜索模型名称...'),
        'text-embedding',
      );

      await waitFor(() => {
        expect(screen.getByText('text-embedding-3')).toBeInTheDocument();
      });
      expect(screen.queryByText('DeepSeek-V3')).not.toBeInTheDocument();
    });

    it('无模型时显示空态引导', async () => {
      mockListModels.mockResolvedValue(makePage([]));
      renderPage();

      await waitFor(() => {
        expect(
          screen.getByText('暂无模型，点击右上角「注册模型」添加第一个'),
        ).toBeInTheDocument();
      });
    });

    it('筛选无结果时提示不同文案', async () => {
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('DeepSeek-V3')).toBeInTheDocument();
      });

      await user.type(
        screen.getByPlaceholderText('搜索模型名称...'),
        '不存在的模型',
      );

      await waitFor(() => {
        expect(
          screen.getByText('当前筛选条件下没有匹配的模型'),
        ).toBeInTheDocument();
      });
    });
  });
});
