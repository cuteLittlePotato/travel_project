'use client';

/**
 * 首页的交互部分（客户端组件）。
 *
 * 为什么要拆成独立组件：
 *   首页需要在服务端拉数据（SSR），但筛选交互必须是客户端的。
 *   把交互隔离在这里，`page.tsx` 保持为纯 Server Component。
 *
 * **首屏不重复请求**：``initialAttractions`` 由服务端传入，
 * 用户未筛选时直接展示，不触发客户端请求（CLAUDE.md 前端规范第 14 条）。
 */
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { AttractionCard } from '@/components/attraction/AttractionCard';
import { CategoryTabs } from '@/components/filter/CategoryTabs';
import { RegionFilter } from '@/components/filter/RegionFilter';
import { http } from '@/lib/api/http';
import {
  attractionsUrl,
  type AttractionList,
  type AttractionQuery,
  type CategoryGrouped,
  type RegionBrief,
} from '@/services/attraction';
import type { ApiResponse } from '@/types/api';

export interface HomeContentProps {
  initialAttractions: AttractionList;
  categories: CategoryGrouped;
  provinces: RegionBrief[];
}

/** 客户端筛选请求：走浏览器同源代理 */
async function fetchAttractions(query: AttractionQuery): Promise<AttractionList> {
  const { data } = await http.get<ApiResponse<AttractionList>>(
    attractionsUrl(query),
  );
  if (data.code !== 0 || !data.data) {
    throw new Error(data.message || '加载景点失败');
  }
  return data.data;
}

export function HomeContent({
  initialAttractions,
  categories,
  provinces,
}: HomeContentProps) {
  const [keywordInput, setKeywordInput] = useState('');
  const [keyword, setKeyword] = useState('');
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [provinceId, setProvinceId] = useState<string | null>(null);
  const [cityId, setCityId] = useState<string | null>(null);

  /** 没有任何筛选条件时用服务端数据，不重复请求 */
  const hasFilters = Boolean(keyword || categoryId || provinceId || cityId);

  const query: AttractionQuery = useMemo(
    () => ({
      keyword: keyword || undefined,
      category_ids: categoryId ?? undefined,
      province_id: provinceId ?? undefined,
      city_id: cityId ?? undefined,
      sort_by: 'popularity',
      page: 1,
      page_size: 12,
    }),
    [keyword, categoryId, provinceId, cityId],
  );

  const filteredQuery = useQuery({
    queryKey: ['attractions', query],
    queryFn: () => fetchAttractions(query),
    enabled: hasFilters,
    staleTime: 30 * 1000,
  });

  const data = hasFilters ? filteredQuery.data : initialAttractions;
  const isLoading = hasFilters && filteredQuery.isLoading;
  const items = data?.items ?? [];

  const handleProvinceChange = (next: string | null) => {
    setProvinceId(next);
    // 切换省份必须清空城市——否则会残留上一个省的城市
    setCityId(null);
  };

  const handleSearch = () => setKeyword(keywordInput.trim());

  return (
    <div className="page-container">
      {/* ---------- Hero + 搜索 ---------- */}
      <section style={{ textAlign: 'center', padding: '48px 0 32px' }}>
        <h1 style={{ fontSize: 40, marginBottom: 12 }}>发现你的下一个旅行目的地</h1>
        <p style={{ fontSize: 16, color: 'var(--color-text-secondary)', marginBottom: 28 }}>
          AI 驱动的旅行推荐与行程规划，为每一次出发提供灵感与方案
        </p>

        <div
          style={{
            display: 'flex',
            maxWidth: 560,
            margin: '0 auto',
            border: '1px solid var(--color-border)',
            borderRadius: 24,
            overflow: 'hidden',
            background: '#fff',
          }}
        >
          <input
            type="search"
            value={keywordInput}
            onChange={(event) => setKeywordInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') handleSearch();
            }}
            placeholder="搜索景点、城市或目的地…"
            style={{
              flex: 1,
              border: 'none',
              outline: 'none',
              padding: '12px 20px',
              fontSize: 15,
            }}
            aria-label="搜索景点"
          />
          <button
            type="button"
            onClick={handleSearch}
            style={{
              border: 'none',
              padding: '0 28px',
              background: '#1677ff',
              color: '#fff',
              fontSize: 15,
              cursor: 'pointer',
            }}
          >
            搜索
          </button>
        </div>
      </section>

      {/* ---------- 筛选器 ---------- */}
      <section style={{ marginBottom: 16 }}>
        <CategoryTabs
          categories={categories}
          selectedId={categoryId}
          onChange={setCategoryId}
        />

        <div
          style={{
            display: 'flex',
            gap: 12,
            flexWrap: 'wrap',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <RegionFilter
            provinces={provinces}
            selectedProvinceId={provinceId}
            selectedCityId={cityId}
            onProvinceChange={handleProvinceChange}
            onCityChange={setCityId}
          />

          {hasFilters && (
            <span style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>
              {isLoading ? '筛选中…' : `共 ${data?.total ?? 0} 个景点`}
            </span>
          )}
        </div>
      </section>

      {/* ---------- 列表 ---------- */}
      <section style={{ marginTop: 24, marginBottom: 64 }}>
        <h2 style={{ fontSize: 22, marginBottom: 20 }}>
          {hasFilters ? '筛选结果' : '🔥 热度排行'}
        </h2>

        {isLoading ? (
          <SkeletonGrid />
        ) : items.length === 0 ? (
          <EmptyState hasFilters={hasFilters} />
        ) : (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
              gap: 20,
            }}
          >
            {items.map((item, index) => (
              <AttractionCard
                key={item.id}
                attraction={item}
                showRank={hasFilters ? undefined : index + 1}
              />
            ))}
          </div>
        )}
      </section>

      {/* ---------- 为你推荐 ---------- */}
      {!hasFilters && (
        <section style={{ marginBottom: 64 }}>
          <h2 style={{ fontSize: 22, marginBottom: 8 }}>✨ 为你推荐</h2>
          <p
            style={{
              fontSize: 13,
              color: 'var(--color-text-secondary)',
              marginBottom: 20,
            }}
          >
            个性化推荐需要登录并积累浏览记录，将在推荐引擎上线后开放。当前展示热度榜单。
          </p>
        </section>
      )}
    </div>
  );
}

function SkeletonGrid() {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
        gap: 20,
      }}
    >
      {Array.from({ length: 8 }).map((_, index) => (
        <div
          key={index}
          style={{
            height: 280,
            borderRadius: 12,
            background: '#f5f5f5',
            animation: 'pulse 1.5s ease-in-out infinite',
          }}
        />
      ))}
    </div>
  );
}

function EmptyState({ hasFilters }: { hasFilters: boolean }) {
  return (
    <div
      style={{
        border: '1px dashed var(--color-border)',
        borderRadius: 12,
        padding: '56px 24px',
        textAlign: 'center',
        color: 'var(--color-text-secondary)',
      }}
    >
      <div style={{ fontSize: 40, marginBottom: 12 }}>🗺️</div>
      <div style={{ fontSize: 16, marginBottom: 6 }}>
        {hasFilters ? '没有符合条件的景点' : '暂无景点'}
      </div>
      <div style={{ fontSize: 13 }}>
        {hasFilters ? '试试换个关键词或放宽筛选条件' : '运营正在录入内容，请稍后再来'}
      </div>
    </div>
  );
}
