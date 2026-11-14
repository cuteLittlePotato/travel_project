/**
 * M02 景点内容服务（API §4.1 / §4.2 / §4.6 / §4.7 / §4.9）。
 *
 * **服务端与客户端分开调用**：
 *   - SSR 页面在服务端执行，不能走浏览器同源代理，需直连后端
 *     （`API_INTERNAL_BASE_URL`）
 *   - 客户端交互（筛选、搜索）走浏览器请求，由 Next rewrites 或 Nginx 代理
 *
 * 两者共用同一套类型与 URL 构造，避免字段定义漂移。
 */
import type { ApiResponse } from '@/types/api';

// ============================================================
// 类型（与后端 attraction/schemas.py 对应）
// ============================================================

export interface RegionBrief {
  id: string;
  name: string;
  code: string;
  level: 1 | 2;
  heat_score: string;
}

export interface CityWithProvince extends RegionBrief {
  province: RegionBrief | null;
}

export interface CategoryBrief {
  id: string;
  name: string;
  category_type: 'theme' | 'level';
  sort_weight: number;
}

export interface AttractionListItem {
  id: string;
  name: string;
  city: RegionBrief | null;
  categories: CategoryBrief[];
  summary: string | null;
  image_url: string | null;
  ticket_price: string | null;
  popularity: number;
  /** M17 尚未开发，当前恒为 null */
  recommend_reason: string | null;
}

export interface AttractionList {
  items: AttractionListItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface OpeningHours {
  mon?: string;
  tue?: string;
  wed?: string;
  thu?: string;
  fri?: string;
  sat?: string;
  sun?: string;
  note?: string;
}

export interface TransportItem {
  id: string;
  name: string;
  transport_type: string | null;
  price: string | null;
  description: string | null;
  operating_hours: Record<string, unknown> | null;
}

export interface AttractionDetail {
  id: string;
  name: string;
  city: CityWithProvince | null;
  categories: CategoryBrief[];
  latitude: string | null;
  longitude: string | null;
  address: string | null;
  summary: string | null;
  description: string | null;
  image_urls: string[];
  ticket_price: string | null;
  opening_hours: OpeningHours | null;
  visit_duration_minutes: number | null;
  best_seasons: string[];
  website: string | null;
  phone: string | null;
  traffic_guide: string | null;
  popularity: number;
  transports: TransportItem[];
  related: {
    persons: Array<{ id: string; name: string; dynasty: string | null; relation: string }>;
    events: Array<{ id: string; name: string; event_time: string | null; relation: string }>;
    cultures: Array<{ id: string; name: string; culture_type: string | null }>;
    nearby_attractions: Array<{ id: string; name: string; distance_km: number }>;
  };
}

export interface CategoryGrouped {
  themes: CategoryBrief[];
  levels: CategoryBrief[];
}

export interface AttractionQuery {
  keyword?: string;
  city_id?: string;
  province_id?: string;
  /** 逗号分隔的分类 ID，多个为「且」关系 */
  category_ids?: string;
  sort_by?: 'popularity' | 'created_at' | 'ticket_price';
  sort_order?: 'asc' | 'desc';
  page?: number;
  page_size?: number;
}

// ============================================================
// URL 构造
// ============================================================

/** 服务端访问后端的基础地址。浏览器端为空（同源代理）。 */
function serverBase(): string {
  return process.env.API_INTERNAL_BASE_URL ?? 'http://127.0.0.1:8000';
}

export function buildQueryString(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : '';
}

export function attractionsUrl(query: AttractionQuery): string {
  return `/api/v1/attractions${buildQueryString(query as Record<string, unknown>)}`;
}

// ============================================================
// 统一取数
// ============================================================

/**
 * 拉取并解包。
 *
 * ``base`` 为空时走相对路径（浏览器同源），否则拼上服务端地址。
 */
async function fetchApi<T>(path: string, base = ''): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    // 列表类数据更新不频繁，30 秒内复用缓存
    next: { revalidate: 30 },
  });

  if (!response.ok) {
    throw new Error(`请求失败：${response.status}`);
  }

  const payload = (await response.json()) as ApiResponse<T>;
  if (payload.code !== 0 || payload.data === null) {
    throw new Error(payload.message || '请求失败');
  }
  return payload.data;
}

// ============================================================
// 接口
// ============================================================

/** 景点列表（API §4.1）。SSR 时传 `base`，客户端不传 */
export function listAttractions(
  query: AttractionQuery = {},
  base = '',
): Promise<AttractionList> {
  return fetchApi<AttractionList>(attractionsUrl(query), base);
}

/** 景点详情（API §4.2）。未上架返回 12001 */
export function getAttraction(id: string, base = ''): Promise<AttractionDetail> {
  return fetchApi<AttractionDetail>(`/api/v1/attractions/${id}`, base);
}

/** 分类列表（API §4.6），按 theme / level 分组 */
export function listCategories(base = ''): Promise<CategoryGrouped> {
  return fetchApi<CategoryGrouped>('/api/v1/attraction-categories', base);
}

export interface RegionList {
  items: RegionBrief[];
}

/** 地区列表（API §4.7） */
export function listRegions(
  params: { level?: number; parent_id?: string } = {},
  base = '',
): Promise<RegionList> {
  return fetchApi<RegionList>(
    `/api/v1/regions${buildQueryString(params)}`,
    base,
  );
}

// ============================================================
// 服务端入口（供 RSC 使用）
// ============================================================

/** 服务端专用：直接访问后端，不经过浏览器代理 */
export const serverApi = {
  listAttractions: (query: AttractionQuery = {}) =>
    listAttractions(query, serverBase()),
  getAttraction: (id: string) => getAttraction(id, serverBase()),
  listCategories: () => listCategories(serverBase()),
  listRegions: (params: { level?: number; parent_id?: string } = {}) =>
    listRegions(params, serverBase()),
};
