'use client';

/**
 * 省份 - 城市二级筛选。
 *
 * 城市列表**按需加载**：省份有 34 个，城市 300+，一次性全拉没必要。
 * 选定省份后再查它的城市；切换省份时清空已选城市（否则会残留
 * 上一个省的城市，筛选结果为空且用户不知道为什么）。
 */
import { useQuery } from '@tanstack/react-query';

import { http } from '@/lib/api/http';
import type { RegionBrief } from '@/services/attraction';
import type { ApiResponse } from '@/types/api';

export interface RegionFilterProps {
  provinces: RegionBrief[];
  selectedProvinceId: string | null;
  selectedCityId: string | null;
  onProvinceChange: (provinceId: string | null) => void;
  onCityChange: (cityId: string | null) => void;
}

/** 客户端拉城市：走浏览器同源代理 */
async function fetchCities(provinceId: string): Promise<RegionBrief[]> {
  const { data } = await http.get<ApiResponse<{ items: RegionBrief[] }>>(
    '/api/v1/regions',
    { params: { parent_id: provinceId, level: 2 } },
  );
  if (data.code !== 0 || !data.data) {
    throw new Error(data.message || '加载城市失败');
  }
  return data.data.items;
}

export function RegionFilter({
  provinces,
  selectedProvinceId,
  selectedCityId,
  onProvinceChange,
  onCityChange,
}: RegionFilterProps) {
  const citiesQuery = useQuery({
    queryKey: ['cities', selectedProvinceId],
    queryFn: () => fetchCities(selectedProvinceId!),
    enabled: Boolean(selectedProvinceId),
    staleTime: 10 * 60 * 1000,
  });

  const selectStyle: React.CSSProperties = {
    padding: '8px 16px',
    border: '1px solid var(--color-border)',
    borderRadius: 8,
    fontSize: 14,
    minWidth: 140,
    background: '#fff',
  };

  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      <select
        value={selectedProvinceId ?? ''}
        onChange={(event) => onProvinceChange(event.target.value || null)}
        style={selectStyle}
        aria-label="选择省份"
      >
        <option value="">全部省份</option>
        {provinces.map((province) => (
          <option key={province.id} value={province.id}>
            {province.name}
          </option>
        ))}
      </select>

      <select
        value={selectedCityId ?? ''}
        onChange={(event) => onCityChange(event.target.value || null)}
        disabled={!selectedProvinceId || citiesQuery.isLoading}
        style={{
          ...selectStyle,
          opacity: selectedProvinceId ? 1 : 0.5,
          cursor: selectedProvinceId ? 'pointer' : 'not-allowed',
        }}
        aria-label="选择城市"
      >
        <option value="">
          {citiesQuery.isLoading ? '加载中…' : '全部城市'}
        </option>
        {(citiesQuery.data ?? []).map((city) => (
          <option key={city.id} value={city.id}>
            {city.name}
          </option>
        ))}
      </select>
    </div>
  );
}
