/**
 * 首页（SSR）。
 *
 * 结构（原型 `prototype/c-end/home.html`）：
 *   搜索框 → 分类标签 → 省份-城市筛选 → 热度排行 → 为你推荐
 *
 * **首屏走 SSR**：景点列表在服务端拉取，搜索引擎与首屏渲染都能拿到
 * 内容（DoD：查看页面源码能看到景点卡片）。
 * **筛选走客户端**：点击分类/地区后由客户端重新请求，不整页刷新。
 *
 * 「为你推荐」需要 M17 推荐引擎，尚未开发——当前复用热度列表，
 * 标注清楚以免被误认为个性化推荐。
 */
import type { Metadata } from 'next';

import { HomeContent } from '@/components/attraction/HomeContent';
import { serverApi } from '@/services/attraction';

export const metadata: Metadata = {
  title: '云游坊 - 智能旅行规划',
  description: '发现好去处，规划好旅程。AI 驱动的旅行推荐与行程规划平台。',
};

/** 每 60 秒重新验证，景点数据不需要秒级更新 */
export const revalidate = 60;

export default async function HomePage() {
  // 并行拉取首屏所需数据，避免串行等待
  const [attractions, categories, provinces] = await Promise.all([
    serverApi.listAttractions({ page: 1, page_size: 12, sort_by: 'popularity' }),
    serverApi.listCategories(),
    serverApi.listRegions({ level: 1 }),
  ]);

  return (
    <HomeContent
      initialAttractions={attractions}
      categories={categories}
      provinces={provinces.items}
    />
  );
}
