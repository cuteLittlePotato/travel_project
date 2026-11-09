/**
 * 省市级联选择器。
 *
 * **用户看到的是名称，存进后端的是行政区划编码**——
 * 「常驻地区」在库里是 `region_code`，用于推荐时按地区匹配。
 * 让用户手填编码既不合理也容易错（110000 是北京，330000 是浙江，
 * 没人应该背这个）。
 *
 * 接口：`GET /api/v1/regions`（API §4.7，公开无需认证）
 */
import { useMemo } from 'react';
import { Cascader } from 'antd';
import { useQuery } from '@tanstack/react-query';

import { http } from '@/lib/api/http';
import type { ApiResponse } from '@/types/api';

interface RegionItem {
  id: string;
  parent_id: string | null;
  name: string;
  code: string;
  level: 1 | 2;
}

interface RegionList {
  items: RegionItem[];
}

interface CascaderOption {
  value: string;
  label: string;
  children?: CascaderOption[];
}

/** 拉取全部地区（省份 + 城市），本地组装成级联树 */
function useRegionTree() {
  const query = useQuery({
    queryKey: ['regions-all'],
    queryFn: async () => {
      const response = await http.get<ApiResponse<RegionList>>('/api/v1/regions');
      const payload = response.data;
      if (payload.code !== 0 || !payload.data) {
        throw new Error(payload.message || '加载地区失败');
      }
      return payload.data.items;
    },
    // 地区字典几乎不变，缓存久一点
    staleTime: 30 * 60 * 1000,
  });

  const options = useMemo<CascaderOption[]>(() => {
    const items: RegionItem[] = query.data ?? [];
    const provinces = items.filter((item) => item.level === 1);
    const citiesByProvince = new Map<string, RegionItem[]>();

    for (const city of items) {
      if (city.level !== 2 || !city.parent_id) continue;
      const list = citiesByProvince.get(city.parent_id) ?? [];
      list.push(city);
      citiesByProvince.set(city.parent_id, list);
    }

    return provinces.map((province) => ({
      // 值用编码——用户选中后提交给后端的就是它
      value: province.code,
      label: province.name,
      children: (citiesByProvince.get(province.id) ?? []).map((city) => ({
        value: city.code,
        label: city.name,
      })),
    }));
  }, [query.data]);

  return { options, isLoading: query.isLoading };
}

export interface RegionCascaderProps {
  /** 行政区划编码，如 110100 */
  value?: string | null;
  onChange?: (code: string | null) => void;
  placeholder?: string;
  disabled?: boolean;
}

/**
 * 把编码还原成级联路径。
 *
 * 编码本身是 6 位数字，无法从它推导出上级编码——
 * 因此从地区树里反查：找到 code 匹配的节点后，
 * 再找它的父节点（城市 → 省）。
 */
function resolvePath(options: CascaderOption[], code: string): string[] | null {
  for (const province of options) {
    if (province.value === code) return [province.value];
    for (const city of province.children ?? []) {
      if (city.value === code) return [province.value, city.value];
    }
  }
  return null;
}

export function RegionCascader({
  value,
  onChange,
  placeholder = '选择省 / 市',
  disabled,
}: RegionCascaderProps) {
  const { options, isLoading } = useRegionTree();

  const cascaderValue = useMemo(() => {
    if (!value) return undefined;
    return resolvePath(options, value) ?? undefined;
  }, [options, value]);

  return (
    <Cascader
      options={options}
      value={cascaderValue}
      onChange={(next) => {
        const selected = next?.[next.length - 1];
        onChange?.(typeof selected === 'string' ? selected : null);
      }}
      placeholder={placeholder}
      loading={isLoading}
      disabled={disabled}
      allowClear
      showSearch={{
        filter: (input, path) =>
          path.some((option) => String(option.label).includes(input)),
      }}
      style={{ width: '100%' }}
    />
  );
}
