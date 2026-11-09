/**
 * 景点图片编辑器的测试。
 *
 * 核心约束：
 *   - 产出是 `string[] | null`，与后端 `image_urls` JSONB 一致
 *   - 第一张是封面，可调整顺序
 *   - 最多 10 张（与后端 max_length 一致）
 *   - 只接受 http(s) 地址
 */
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';

import { ImageUrlsField } from './ImageUrlsField';

function renderField(
  value: string[] | null = null,
  onChange?: (v: string[] | null) => void,
) {
  return render(
    <ConfigProvider locale={zhCN}>
      <AntdApp>
        <ImageUrlsField value={value} onChange={onChange} />
      </AntdApp>
    </ConfigProvider>,
  );
}

const IMG1 = 'https://example.com/a.jpg';
const IMG2 = 'https://example.com/b.jpg';

describe('ImageUrlsField', () => {
  describe('空态', () => {
    it('无图片时显示占位', () => {
      renderField();
      expect(screen.getByText('暂无图片')).toBeInTheDocument();
    });

    it('提示最多张数', () => {
      renderField();
      expect(screen.getByText(/最多 10 张/)).toBeInTheDocument();
    });
  });

  describe('添加图片', () => {
    it('输入合法 URL 后添加', async () => {
      const onChange = vi.fn();
      const user = userEvent.setup();
      renderField(null, onChange);

      await user.type(screen.getByPlaceholderText(/example\.com/), IMG1);
      await user.click(screen.getByRole('button', { name: /添\s*加/ }));

      expect(onChange).toHaveBeenCalledWith([IMG1]);
    });

    it('回车也能添加', async () => {
      const onChange = vi.fn();
      const user = userEvent.setup();
      renderField(null, onChange);

      await user.type(screen.getByPlaceholderText(/example\.com/), `${IMG1}{enter}`);

      expect(onChange).toHaveBeenCalledWith([IMG1]);
    });

    it('拒绝非 http(s) 地址', async () => {
      const onChange = vi.fn();
      const user = userEvent.setup();
      renderField(null, onChange);

      await user.type(screen.getByPlaceholderText(/example\.com/), 'ftp://a.com/x.jpg');
      await user.click(screen.getByRole('button', { name: /添\s*加/ }));

      expect(onChange).not.toHaveBeenCalled();
      expect(screen.getByText('图片地址必须以 http:// 或 https:// 开头')).toBeInTheDocument();
    });

    it('拒绝空输入', async () => {
      const onChange = vi.fn();
      const user = userEvent.setup();
      renderField(null, onChange);

      await user.click(screen.getByRole('button', { name: /添\s*加/ }));

      expect(onChange).not.toHaveBeenCalled();
      expect(screen.getByText('请输入图片地址')).toBeInTheDocument();
    });

    it('拒绝重复图片', async () => {
      const onChange = vi.fn();
      const user = userEvent.setup();
      renderField([IMG1], onChange);

      await user.type(screen.getByPlaceholderText(/example\.com/), IMG1);
      await user.click(screen.getByRole('button', { name: /添\s*加/ }));

      expect(onChange).not.toHaveBeenCalled();
      expect(screen.getByText('该图片已添加')).toBeInTheDocument();
    });

    it('超过 10 张拒绝', async () => {
      const onChange = vi.fn();
      const user = userEvent.setup();
      const ten = Array.from({ length: 10 }, (_, i) => `https://example.com/${i}.jpg`);

      renderField(ten, onChange);

      await user.type(screen.getByPlaceholderText(/example\.com/), 'https://example.com/new.jpg');
      await user.click(screen.getByRole('button', { name: /添\s*加/ }));

      expect(onChange).not.toHaveBeenCalled();
      expect(screen.getByText('最多添加 10 张图片')).toBeInTheDocument();
    });

    it('添加后清空输入框', async () => {
      const user = userEvent.setup();

      function Controlled() {
        const [value, setValue] = React.useState<string[] | null>(null);
        return <ImageUrlsField value={value} onChange={setValue} />;
      }

      render(
        <ConfigProvider locale={zhCN}>
          <AntdApp>
            <Controlled />
          </AntdApp>
        </ConfigProvider>,
      );

      const input = screen.getByPlaceholderText(/example\.com/) as HTMLInputElement;
      await user.type(input, IMG1);
      await user.click(screen.getByRole('button', { name: /添\s*加/ }));

      expect(input.value).toBe('');
    });
  });

  describe('封面标记', () => {
    it('第一张标记为封面', () => {
      renderField([IMG1, IMG2]);
      expect(screen.getByText('封面')).toBeInTheDocument();
    });

    it('只有第一张是封面', () => {
      renderField([IMG1, IMG2, 'https://example.com/c.jpg']);
      expect(screen.getAllByText('封面')).toHaveLength(1);
    });
  });

  describe('排序', () => {
    it('下移交换位置', async () => {
      const onChange = vi.fn();
      const user = userEvent.setup();
      renderField([IMG1, IMG2], onChange);

      const cards = screen.getAllByTitle('下移');
      await user.click(cards[0]!);

      expect(onChange).toHaveBeenCalledWith([IMG2, IMG1]);
    });

    it('上移交换位置', async () => {
      const onChange = vi.fn();
      const user = userEvent.setup();
      renderField([IMG1, IMG2], onChange);

      const cards = screen.getAllByTitle('上移');
      await user.click(cards[1]!);

      expect(onChange).toHaveBeenCalledWith([IMG2, IMG1]);
    });

    it('第一张不能上移', () => {
      renderField([IMG1, IMG2]);
      const ups = screen.getAllByTitle('上移');
      expect(ups[0]).toBeDisabled();
    });

    it('最后一张不能下移', () => {
      renderField([IMG1, IMG2]);
      const downs = screen.getAllByTitle('下移');
      expect(downs[downs.length - 1]).toBeDisabled();
    });
  });

  describe('删除', () => {
    it('删除指定图片', async () => {
      const onChange = vi.fn();
      const user = userEvent.setup();
      renderField([IMG1, IMG2], onChange);

      const deletes = screen.getAllByTitle('删除');
      await user.click(deletes[0]!);

      expect(onChange).toHaveBeenCalledWith([IMG2]);
    });

    it('删完最后一张返回 null 而非空数组', async () => {
      const onChange = vi.fn();
      const user = userEvent.setup();
      renderField([IMG1], onChange);

      await user.click(screen.getAllByTitle('删除')[0]!);

      expect(onChange).toHaveBeenCalledWith(null);
    });
  });

  describe('回填', () => {
    it('已有图片时渲染缩略图', () => {
      const { container } = renderField([IMG1, IMG2]);

      // antd Image 内部会额外渲染 img（预览层等），
      // 因此按容器内的图片卡片数量断言，而不是全局 img 数量
      const cards = container.querySelectorAll('.ant-image');
      expect(cards).toHaveLength(2);
    });
  });
});
