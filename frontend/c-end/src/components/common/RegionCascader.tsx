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

/**
 * 回传什么值。
 *
 * 项目里有两个「地区」字段，存的格式不同：
 *   - ``user.region_code``：存行政区划编码（VARCHAR(20)）
 *   - ``travel_profile.departure_city``：存城市名称（VARCHAR(50)）
 *
 * 与其让两个字段各自实现一套选择器，不如让本组件支持两种回传格式。
 * 新字段建议统一用编码——名称会因运营改名而失效。
 */
export type RegionValueField = 'code' | 'name';

export interface RegionCascaderProps {
  /** 已选值。``valueField='code'`` 时为编码，``'name'`` 时为城市名 */
  value?: string | null;
  onChange?: (value: string | null) => void;
  /** 回传编码还是名称，默认 ``code`` */
  valueField?: RegionValueField;
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
function resolvePath(
  options: CascaderOption[],
  target: string,
  valueField: RegionValueField,
): string[] | null {
  // ``code`` 模式按 value 匹配；``name`` 模式按 label 匹配。
  // 名称模式下城市优先于省——「北京市」既是省名也是市名，
  // 用户选的几乎总是市。
  const matches = (option: CascaderOption) =>
    valueField === 'code' ? option.value === target : option.label === target;

  for (const province of options) {
    for (const city of province.children ?? []) {
      if (matches(city)) return [province.value, city.value];
    }
    if (matches(province)) return [province.value];
  }
  return null;
}

/** 按编码找选项的 label（用于 ``valueField='name'`` 时回传名称） */
function findLabel(options: CascaderOption[], value: string): string | null {
  for (const province of options) {
    if (province.value === value) return province.label;
    for (const city of province.children ?? []) {
      if (city.value === value) return city.label;
    }
  }
  return null;
}

export function RegionCascader({
  value,
  onChange,
  valueField = 'code',
  placeholder = '选择省 / 市',
  disabled,
}: RegionCascaderProps) {
  const { options, isLoading } = useRegionTree();

  const cascaderValue = useMemo(() => {
    if (!value) return undefined;
    return resolvePath(options, value, valueField) ?? undefined;
  }, [options, value, valueField]);

  return (
    <Cascader
      options={options}
      value={cascaderValue}
      onChange={(next) => {
        const selected = next?.[next.length - 1];
        if (typeof selected !== 'string') {
          onChange?.(null);
          return;
        }
        // 按约定格式回传：编码或名称
        onChange?.(
          valueField === 'code' ? selected : findLabel(options, selected),
        );
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
