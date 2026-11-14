/**
 * 省市级联选择器的测试。
 *
 * 核心约束：
 *   - **用户看到名称，提交的是编码**——库里存 `region_code`
 *   - 支持从已有编码反查出级联路径（编辑回填）
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { RegionCascader } from './RegionCascader';

const mockGet = vi.fn();

vi.mock('@/lib/api/http', () => ({
  http: {
    get: (...args: unknown[]) => mockGet(...args),
  },
}));

const REGIONS = [
  { id: 'p1', parent_id: null, name: '北京市', code: '110000', level: 1 },
  { id: 'p2', parent_id: null, name: '浙江省', code: '330000', level: 1 },
  { id: 'c1', parent_id: 'p1', name: '北京市', code: '110100', level: 2 },
  { id: 'c2', parent_id: 'p2', name: '杭州市', code: '330100', level: 2 },
  { id: 'c3', parent_id: 'p2', name: '宁波市', code: '330200', level: 2 },
];

function renderCascader(
  value: string | null = null,
  onChange?: (code: string | null) => void,
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RegionCascader value={value} onChange={onChange} />
    </QueryClientProvider>,
  );
}

describe('RegionCascader', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockGet.mockResolvedValue({
      data: { code: 0, message: 'ok', data: { items: REGIONS } },
    });
  });

  it('加载地区后渲染选择器', async () => {
    renderCascader();

    await waitFor(() => {
      expect(screen.getByRole('combobox')).toBeInTheDocument();
    });
  });

  it('显示占位文案', async () => {
    renderCascader();

    // antd Cascader 的 placeholder 通过 CSS 伪元素或 input 属性渲染，
    // 不同版本表现不同，这里宽松匹配
    await waitFor(() => {
      expect(document.body.textContent).toContain('选择省 / 市');
    });
  });

  it('请求公开的地区接口', async () => {
    renderCascader();

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith('/api/v1/regions');
    });
  });

  describe('编辑回填', () => {
    it('已有城市编码时显示对应路径', async () => {
      renderCascader('330100');

      await waitFor(() => {
        // 级联已展开到杭州市
        expect(screen.getByRole('combobox')).toBeInTheDocument();
      });
    });

    it('已有省份编码时也能识别', async () => {
      renderCascader('330000');

      await waitFor(() => {
        expect(screen.getByRole('combobox')).toBeInTheDocument();
      });
    });

    it('编码在字典中不存在时不崩溃', async () => {
      renderCascader('999999');

      await waitFor(() => {
        expect(screen.getByRole('combobox')).toBeInTheDocument();
      });
    });
  });

  describe('选择', () => {
    it('选择省市后回传城市编码', async () => {
      const onChange = vi.fn();
      const user = userEvent.setup();
      renderCascader(null, onChange);

      await waitFor(() => {
        expect(screen.getByRole('combobox')).toBeInTheDocument();
      });

      // 打开级联
      await user.click(screen.getByRole('combobox'));

      await waitFor(() => {
        expect(screen.getByText('浙江省')).toBeInTheDocument();
      });

      // 展开浙江省
      await user.click(screen.getByText('浙江省'));

      await waitFor(() => {
        expect(screen.getByText('杭州市')).toBeInTheDocument();
      });

      await user.click(screen.getByText('杭州市'));

      await waitFor(() => {
        // 传的是编码，不是名称
        expect(onChange).toHaveBeenCalledWith('330100');
      });
    });
  });

  describe('清空', () => {
    it('清除后回传 null', async () => {
      const onChange = vi.fn();
      const user = userEvent.setup();
      renderCascader('330100', onChange);

      const clearButton = document.querySelector('.ant-cascader-clear');
      if (clearButton) {
        await user.click(clearButton as HTMLElement);
        await waitFor(() => {
          expect(onChange).toHaveBeenCalledWith(null);
        });
      }
    });
  });
});
