/**
 * 景点详情页组件的测试（M02-T10 DoD）。
 *
 * DoD：
 *   - 详情页 SSR 输出核心信息（已在构建阶段验证页面源码）
 *   - 关联内容四个板块按原型展示（组件测试）
 *   - 「查看知识图谱」跳转 /knowledge-graph/{id}（集成测试）
 *   - 与原型 attraction-detail.html 区块一致
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { DetailGallery } from './DetailGallery';
import { QuickActions } from './QuickActions';
import { RelatedContent } from './RelatedContent';
import type { AttractionDetail } from '@/services/attraction';

type Related = AttractionDetail['related'];

const EMPTY_RELATED: Related = {
  persons: [],
  events: [],
  cultures: [],
  nearby_attractions: [],
};

describe('DetailGallery', () => {
  it('无图时降级为渐变背景（含景点名前两字）', () => {
    render(<DetailGallery name="故宫博物院" imageUrls={[]} />);

    expect(screen.getByText('故宫')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /暂无图片/ })).toBeInTheDocument();
  });

  it('单图直接铺满', () => {
    const { container } = render(
      <DetailGallery name="故宫" imageUrls={['https://example.com/1.jpg']} />,
    );

    expect(container.querySelectorAll('img')).toHaveLength(1);
    // 无缩略图条
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('多图渲染缩略图条', () => {
    render(
      <DetailGallery
        name="故宫"
        imageUrls={[
          'https://example.com/1.jpg',
          'https://example.com/2.jpg',
          'https://example.com/3.jpg',
        ]}
      />,
    );

    expect(screen.getAllByRole('button')).toHaveLength(3);
  });

  it('点击缩略图切换大图', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <DetailGallery
        name="故宫"
        imageUrls={['https://example.com/1.jpg', 'https://example.com/2.jpg']}
      />,
    );

    const thumbs = screen.getAllByRole('button');
    await user.click(thumbs[1]!);

    const mainImage = container.querySelector('img');
    expect(mainImage).toHaveAttribute('src', 'https://example.com/2.jpg');
  });

  it('当前缩略图有选中标记', () => {
    render(
      <DetailGallery
        name="故宫"
        imageUrls={['https://example.com/1.jpg', 'https://example.com/2.jpg']}
      />,
    );

    const thumbs = screen.getAllByRole('button');
    expect(thumbs[0]).toHaveAttribute('aria-pressed', 'true');
    expect(thumbs[1]).toHaveAttribute('aria-pressed', 'false');
  });
});

describe('RelatedContent（DoD：四个板块）', () => {
  it('渲染四个板块标题', () => {
    render(<RelatedContent related={EMPTY_RELATED} />);

    expect(screen.getByText('相关人物')).toBeInTheDocument();
    expect(screen.getByText('历史事件')).toBeInTheDocument();
    expect(screen.getByText('相关文化')).toBeInTheDocument();
    expect(screen.getByText('周边景点')).toBeInTheDocument();
  });

  it('无数据时每块显示「暂无数据」', () => {
    render(<RelatedContent related={EMPTY_RELATED} />);

    expect(screen.getAllByText('暂无数据')).toHaveLength(4);
  });

  it('渲染人物（含朝代与关系）', () => {
    render(
      <RelatedContent
        related={{
          ...EMPTY_RELATED,
          persons: [{ id: 'p1', name: '朱棣', dynasty: '明朝', relation: '建造者' }],
        }}
      />,
    );

    expect(screen.getByText('朱棣')).toBeInTheDocument();
    expect(screen.getByText(/明朝/)).toBeInTheDocument();
    expect(screen.getByText(/建造者/)).toBeInTheDocument();
  });

  it('渲染历史事件', () => {
    render(
      <RelatedContent
        related={{
          ...EMPTY_RELATED,
          events: [
            { id: 'e1', name: '紫禁城建成', event_time: '1420年', relation: '事件发生地' },
          ],
        }}
      />,
    );

    expect(screen.getByText('紫禁城建成')).toBeInTheDocument();
    expect(screen.getByText(/1420年/)).toBeInTheDocument();
  });

  it('渲染文化', () => {
    render(
      <RelatedContent
        related={{
          ...EMPTY_RELATED,
          cultures: [{ id: 'c1', name: '明清建筑', culture_type: 'architecture' }],
        }}
      />,
    );

    expect(screen.getByText('明清建筑')).toBeInTheDocument();
    expect(screen.getByText(/architecture/)).toBeInTheDocument();
  });

  it('周边景点带距离且可跳转', () => {
    render(
      <RelatedContent
        related={{
          ...EMPTY_RELATED,
          nearby_attractions: [{ id: 'n1', name: '景山公园', distance_km: 0.5 }],
        }}
      />,
    );

    const link = screen.getByRole('link', { name: /景山公园/ });
    expect(link).toHaveAttribute('href', '/attraction/n1');
    expect(screen.getByText(/0\.5 km/)).toBeInTheDocument();
  });
});

describe('QuickActions', () => {
  const baseProps = {
    attractionId: 'a1',
    attractionName: '故宫博物院',
    isLoggedIn: true,
  };

  it('渲染四个操作', () => {
    render(<QuickActions {...baseProps} />);

    expect(screen.getByText('加入旅游计划')).toBeInTheDocument();
    expect(screen.getByText('标记为去过')).toBeInTheDocument();
    expect(screen.getByText('查看知识图谱')).toBeInTheDocument();
    expect(screen.getByText('咨询 AI 助手')).toBeInTheDocument();
  });

  it('**「查看知识图谱」跳转正确路径**（DoD）', () => {
    render(<QuickActions {...baseProps} />);

    const link = screen.getByRole('link', { name: /查看知识图谱/ });
    expect(link).toHaveAttribute('href', '/knowledge-graph/a1');
  });

  it('未开发的功能按钮禁用并说明原因', () => {
    render(<QuickActions {...baseProps} />);

    const planButton = screen.getByRole('button', { name: /加入旅游计划/ });
    expect(planButton).toBeDisabled();
    expect(planButton).toHaveAttribute('title', '行程规划功能开发中');

    const footprintButton = screen.getByRole('button', { name: /标记为去过/ });
    expect(footprintButton).toBeDisabled();
  });

  it('未登录时咨询助手提示登录', () => {
    render(<QuickActions {...baseProps} isLoggedIn={false} />);

    const chatButton = screen.getByRole('button', { name: /咨询 AI 助手/ });
    expect(chatButton).toHaveAttribute('title', '登录后可使用');
  });

  it('已登录时咨询助手提示开发中', () => {
    render(<QuickActions {...baseProps} isLoggedIn />);

    const chatButton = screen.getByRole('button', { name: /咨询 AI 助手/ });
    expect(chatButton).toHaveAttribute('title', '对话功能开发中');
  });
});
