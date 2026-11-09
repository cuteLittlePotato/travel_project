/**
 * M11 基础数据服务（API §12.1 ~ §12.36）。
 */
import { request } from '@/services/http';
import type { PageData } from '@/types/api';

// ============================================================
// 类型
// ============================================================

export interface Region {
  id: string;
  parent_id: string | null;
  name: string;
  level: number;
  code: string;
  description: string | null;
  cover_image_url: string | null;
  heat_score: string;
  sort_weight: number;
  created_at: string;
  updated_at: string;
}

export interface ProvinceListItem extends Region {
  city_count: number;
}

export interface CityListItem extends Region {
  province_name: string | null;
  attraction_count: number;
}

export interface Category {
  id: string;
  name: string;
  category_type: 'theme' | 'level';
  parent_id: string | null;
  description: string | null;
  sort_weight: number;
  created_at: string;
  updated_at: string;
  attraction_count?: number;
}

export interface Attraction {
  id: string;
  name: string;
  city_id: string;
  city_name: string | null;
  summary: string | null;
  cover_image_url: string | null;
  ticket_price: string | null;
  base_popularity: string;
  final_popularity: string | null;
  is_published: boolean;
  sort_weight: number;
  categories: string[];
  created_at: string;
}

export interface AttractionDetail extends Attraction {
  latitude: string | null;
  longitude: string | null;
  address: string | null;
  description: string | null;
  image_urls: string[] | null;
  opening_hours: Record<string, unknown> | null;
  visit_duration_minutes: number | null;
  best_seasons: string[] | null;
  website: string | null;
  phone: string | null;
  traffic_guide: string | null;
  category_ids: string[];
  updated_at: string;
}

export interface AttractionPayload {
  name: string;
  city_id: string;
  latitude?: string | null;
  longitude?: string | null;
  address?: string | null;
  summary?: string | null;
  description?: string | null;
  image_urls?: string[] | null;
  ticket_price?: string | null;
  opening_hours?: Record<string, unknown> | null;
  visit_duration_minutes?: number | null;
  best_seasons?: string[] | null;
  website?: string | null;
  phone?: string | null;
  traffic_guide?: string | null;
  base_popularity?: string;
  is_published?: boolean;
  sort_weight?: number;
  category_ids?: string[];
}

// ============================================================
// 地区
// ============================================================

export interface RegionPayload {
  name: string;
  code: string;
  description?: string | null;
  cover_image_url?: string | null;
  heat_score?: string;
  sort_weight?: number;
}

/** 创建城市时 parent_id 必填（API §12.6） */
export interface CityCreatePayload extends RegionPayload {
  parent_id: string;
}

export function listProvinces(keyword?: string): Promise<{ items: ProvinceListItem[] }> {
  return request({ url: '/regions/provinces', params: { keyword } });
}

export function createProvince(payload: RegionPayload): Promise<Region> {
  return request({ url: '/regions/provinces', method: 'POST', data: payload });
}

export async function updateProvince(id: string, payload: RegionPayload): Promise<void> {
  await request<null>({ url: `/regions/provinces/${id}`, method: 'PUT', data: payload });
}

export async function deleteProvince(id: string): Promise<void> {
  await request<null>({ url: `/regions/provinces/${id}`, method: 'DELETE' });
}

export function listCities(params: {
  province_id?: string;
  keyword?: string;
  page?: number;
  page_size?: number;
}): Promise<PageData<CityListItem>> {
  return request({ url: '/regions/cities', params });
}

export function createCity(payload: CityCreatePayload): Promise<Region> {
  return request({ url: '/regions/cities', method: 'POST', data: payload });
}

export async function updateCity(id: string, payload: RegionPayload): Promise<void> {
  await request<null>({ url: `/regions/cities/${id}`, method: 'PUT', data: payload });
}

export async function deleteCity(id: string): Promise<void> {
  await request<null>({ url: `/regions/cities/${id}`, method: 'DELETE' });
}

// ============================================================
// 分类
// ============================================================

export function listCategories(categoryType?: 'theme' | 'level'): Promise<{
  items: Category[];
}> {
  return request({
    url: '/attraction-categories',
    params: { category_type: categoryType },
  });
}

export interface CategoryPayload {
  name: string;
  description?: string | null;
  sort_weight?: number;
}

export interface CategoryCreatePayload extends CategoryPayload {
  category_type: 'theme' | 'level';
  parent_id?: string | null;
}

export function createCategory(payload: CategoryCreatePayload): Promise<Category> {
  return request({ url: '/attraction-categories', method: 'POST', data: payload });
}

/** 更新时 `category_type` 不可改（后端 CategoryUpdate 已排除该字段） */
export async function updateCategory(id: string, payload: CategoryPayload): Promise<void> {
  await request<null>({
    url: `/attraction-categories/${id}`,
    method: 'PUT',
    data: payload,
  });
}

export async function deleteCategory(id: string): Promise<void> {
  await request<null>({ url: `/attraction-categories/${id}`, method: 'DELETE' });
}

// ============================================================
// 景点
// ============================================================

export function listAttractions(params: {
  city_id?: string;
  category_id?: string;
  keyword?: string;
  is_published?: boolean;
  page?: number;
  page_size?: number;
}): Promise<PageData<Attraction>> {
  return request({ url: '/attractions', params });
}

export function getAttraction(id: string): Promise<AttractionDetail> {
  return request({ url: `/attractions/${id}` });
}

export function createAttraction(payload: AttractionPayload): Promise<Attraction> {
  return request({ url: '/attractions', method: 'POST', data: payload });
}

export async function updateAttraction(
  id: string,
  payload: AttractionPayload,
): Promise<void> {
  await request<null>({ url: `/attractions/${id}`, method: 'PUT', data: payload });
}

export async function deleteAttraction(id: string): Promise<void> {
  await request<null>({ url: `/attractions/${id}`, method: 'DELETE' });
}

/** 批量设置分类（整体替换语义，API §12.17.1） */
export async function setAttractionCategories(
  id: string,
  categoryIds: string[],
): Promise<void> {
  await request<null>({
    url: `/attractions/${id}/categories`,
    method: 'PUT',
    data: { category_ids: categoryIds },
  });
}

// ============================================================
// 餐厅
// ============================================================

/** 餐厅列表项——只含表格展示所需字段（API §12.20） */
export interface Restaurant {
  id: string;
  name: string;
  city_id: string;
  city_name: string | null;
  cuisine_type: string | null;
  address: string | null;
  avg_cost: string | null;
  /** 营业时间，结构见 OpeningHours（{mon: "09:00-17:00", note: "..."}） */
  business_hours: Record<string, string> | null;
  cover_image_url: string | null;
  is_published: boolean;
  created_at: string;
}

/** 餐厅详情——含全部可编辑字段（API §12.20.1），供编辑回填 */
export interface RestaurantDetail extends Restaurant {
  latitude: string | null;
  longitude: string | null;
  summary: string | null;
  signature_dishes: string[] | null;
  need_reservation: boolean;
  phone: string | null;
  image_urls: string[] | null;
  updated_at: string;
}

export interface RestaurantPayload {
  name: string;
  city_id: string;
  cuisine_type?: string | null;
  latitude?: string | null;
  longitude?: string | null;
  address?: string | null;
  summary?: string | null;
  avg_cost?: string | null;
  business_hours?: Record<string, unknown> | null;
  signature_dishes?: string[] | null;
  image_urls?: string[] | null;
  need_reservation?: boolean;
  phone?: string | null;
  is_published?: boolean;
}

/** 餐厅详情（API §12.20.1）。编辑表单回填用 */
export function getRestaurant(id: string): Promise<RestaurantDetail> {
  return request({ url: `/restaurants/${id}` });
}

export function listRestaurants(params: {
  city_id?: string;
  keyword?: string;
  is_published?: boolean;
  page?: number;
  page_size?: number;
}): Promise<PageData<Restaurant>> {
  return request({ url: '/restaurants', params });
}

export function createRestaurant(payload: RestaurantPayload): Promise<Restaurant> {
  return request({ url: '/restaurants', method: 'POST', data: payload });
}

export async function updateRestaurant(
  id: string,
  payload: RestaurantPayload,
): Promise<void> {
  await request<null>({ url: `/restaurants/${id}`, method: 'PUT', data: payload });
}

export async function deleteRestaurant(id: string): Promise<void> {
  await request<null>({ url: `/restaurants/${id}`, method: 'DELETE' });
}

// ============================================================
// 酒店
// ============================================================

/** 酒店列表项——只含表格展示所需字段（API §12.24） */
export interface Hotel {
  id: string;
  name: string;
  city_id: string;
  city_name: string | null;
  star_level: string | null;
  address: string | null;
  min_price: string | null;
  max_price: string | null;
  cover_image_url: string | null;
  is_published: boolean;
  created_at: string;
}

/** 酒店详情——含全部可编辑字段（API §12.24.1） */
export interface HotelDetail extends Hotel {
  latitude: string | null;
  longitude: string | null;
  summary: string | null;
  room_types: Array<Record<string, unknown>> | null;
  facilities: string[] | null;
  booking_url: string | null;
  phone: string | null;
  image_urls: string[] | null;
  updated_at: string;
}

export interface HotelPayload {
  name: string;
  city_id: string;
  star_level?: string | null;
  latitude?: string | null;
  longitude?: string | null;
  address?: string | null;
  summary?: string | null;
  min_price?: string | null;
  max_price?: string | null;
  room_types?: Array<Record<string, unknown>> | null;
  facilities?: string[] | null;
  image_urls?: string[] | null;
  booking_url?: string | null;
  phone?: string | null;
  is_published?: boolean;
}

/** 酒店详情（API §12.24.1） */
export function getHotel(id: string): Promise<HotelDetail> {
  return request({ url: `/hotels/${id}` });
}

export function listHotels(params: {
  city_id?: string;
  keyword?: string;
  is_published?: boolean;
  page?: number;
  page_size?: number;
}): Promise<PageData<Hotel>> {
  return request({ url: '/hotels', params });
}

export function createHotel(payload: HotelPayload): Promise<Hotel> {
  return request({ url: '/hotels', method: 'POST', data: payload });
}

export async function updateHotel(id: string, payload: HotelPayload): Promise<void> {
  await request<null>({ url: `/hotels/${id}`, method: 'PUT', data: payload });
}

export async function deleteHotel(id: string): Promise<void> {
  await request<null>({ url: `/hotels/${id}`, method: 'DELETE' });
}

// ============================================================
// 活动
// ============================================================

export type ActivityType = 'discount' | 'festival' | 'exhibition' | 'other';
export type ActivityStatus = 'upcoming' | 'ongoing' | 'ended';

export interface Activity {
  id: string;
  title: string;
  description: string | null;
  cover_image_url: string | null;
  activity_type: ActivityType | null;
  start_date: string;
  end_date: string;
  city_id: string | null;
  attraction_id: string | null;
  detail_url: string | null;
  is_published: boolean;
  sort_weight: number;
  created_by: string;
  created_at: string;
  updated_at: string;
  /** 实时计算，不存库 */
  status: ActivityStatus;
}

export interface ActivityPayload {
  title: string;
  description?: string | null;
  cover_image_url?: string | null;
  activity_type?: ActivityType | null;
  start_date: string;
  end_date: string;
  city_id?: string | null;
  attraction_id?: string | null;
  detail_url?: string | null;
  is_published?: boolean;
  sort_weight?: number;
}

/** 活动详情（API §12.31.1） */
export function getActivity(id: string): Promise<Activity> {
  return request({ url: `/activities/${id}` });
}

export function listActivities(params: {
  city_id?: string;
  is_published?: boolean;
  page?: number;
  page_size?: number;
}): Promise<PageData<Activity>> {
  return request({ url: '/activities', params });
}

export function createActivity(payload: ActivityPayload): Promise<Activity> {
  return request({ url: '/activities', method: 'POST', data: payload });
}

export async function updateActivity(id: string, payload: ActivityPayload): Promise<void> {
  await request<null>({ url: `/activities/${id}`, method: 'PUT', data: payload });
}

export async function setActivityPublished(
  id: string,
  isPublished: boolean,
): Promise<void> {
  await request<null>({
    url: `/activities/${id}/publish`,
    method: 'PATCH',
    data: { is_published: isPublished },
  });
}

export async function deleteActivity(id: string): Promise<void> {
  await request<null>({ url: `/activities/${id}`, method: 'DELETE' });
}
