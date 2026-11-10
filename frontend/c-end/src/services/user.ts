/**
 * 用户资料服务（API §3.8 ~ §3.14）。
 *
 * 与 `services/auth.ts` 的分工：那边是登录相关的公开接口，
 * 这边是需要登录的用户自身数据。
 */
import { http, parseApiError } from '@/lib/api/http';
import type { ApiResponse } from '@/types/api';

// ============================================================
// 类型（与后端 schemas.py 对应）
// ============================================================

export type Gender = 'male' | 'female' | 'secret';
export type Visibility = 'public' | 'friends' | 'private';
export type BudgetLevel = 'economy' | 'moderate' | 'comfortable' | 'luxury';
export type CompanionType = 'solo' | 'couple' | 'family' | 'friends';

export interface UserBinding {
  provider: string;
  provider_uid: string;
  is_primary: boolean;
}

export interface UserProfile {
  id: string;
  username: string;
  nickname: string;
  avatar_url: string | null;
  gender: Gender | null;
  region_code: string | null;
  /** 地区层级名称，由后端解析。编码在字典中不存在时为 null */
  region: {
    code: string;
    province: string;
    city: string;
    display: string;
  } | null;
  status: string;
  created_at: string;
  bindings: UserBinding[];
}

export interface UpdateProfilePayload {
  nickname?: string | null;
  avatar_url?: string | null;
  gender?: Gender | null;
  region_code?: string | null;
}

export interface TravelProfile {
  travel_types: string[];
  travel_styles: string[];
  budget_level: BudgetLevel | null;
  companion_type: CompanionType | null;
  preferred_seasons: string[];
  /** 出发城市编码（GB/T 2260），与 user.region_code 同一套格式 */
  departure_city_code: string | null;
  /** 后端解析出的城市信息，编码无效时为 null。**仅响应有，提交时不要传** */
  departure_city_info?: { code: string; name: string } | null;
}

/**
 * 更新旅游偏好的请求体。
 *
 * 排除 ``departure_city``——它是后端按编码解析出来的展示字段，
 * 前端提交时不该回传（回传也会被 Pydantic 忽略，但类型上明确排除更清晰）。
 */
export type UpdateTravelProfilePayload = Omit<TravelProfile, 'departure_city_info'>;

export interface UserSettings {
  profile_visibility: Visibility;
  footprint_visibility: Visibility;
  plan_visibility: Visibility;
  allow_recommendation: boolean;
  allow_notification: boolean;
}

export type UpdateSettingsPayload = Partial<UserSettings>;

// ============================================================
// 错误
// ============================================================

export class UserApiError extends Error {
  constructor(
    readonly code: number,
    message: string,
  ) {
    super(message);
    this.name = 'UserApiError';
  }
}

/**
 * 解包统一响应。
 *
 * 注意：``code === 0`` 但 ``data === null`` 是**合法**的——
 * 更新类接口（HTTP 204 语义）返回的就是 null，不能当错误处理。
 */
async function unwrap<T>(
  request: Promise<{ data: ApiResponse<T>; status?: number }>,
): Promise<T> {
  try {
    const response = await request;

    // 204 No Content 没有响应体（PUT/PATCH/DELETE 的常规返回），
    // 此时 response.data 是空字符串。直接读 data.code 会得到 undefined，
    // 被 `!== 0` 误判为失败，抛出 message 为 undefined 的 UserApiError——
    // 前端表现为一个**只有红叉、没有文字**的空白错误提示。
    if (response.status === 204 || !response.data) {
      return null as T;
    }

    const { data } = response;
    if (data.code !== 0) {
      throw new UserApiError(data.code, data.message);
    }
    return data.data as T;
  } catch (error) {
    if (error instanceof UserApiError) throw error;
    const parsed = parseApiError(error);
    throw new UserApiError(parsed.code, parsed.message);
  }
}

// ============================================================
// 基础资料
// ============================================================

export function getProfile(): Promise<UserProfile> {
  return unwrap(http.get<ApiResponse<UserProfile>>('/api/v1/users/me'));
}

export function updateProfile(payload: UpdateProfilePayload): Promise<UserProfile> {
  return unwrap(http.patch<ApiResponse<UserProfile>>('/api/v1/users/me', payload));
}

// ============================================================
// 旅游偏好
// ============================================================

export function getTravelProfile(): Promise<TravelProfile> {
  return unwrap(http.get<ApiResponse<TravelProfile>>('/api/v1/users/me/profile'));
}

/**
 * 更新旅游偏好。
 *
 * **整体替换语义**（API §3.12）：未传的字段会被后端清空。
 * 因此调用方必须传完整对象，不能只传想改的字段。
 */
export async function updateTravelProfile(
  payload: UpdateTravelProfilePayload,
): Promise<void> {
  await unwrap<null>(http.put<ApiResponse<null>>('/api/v1/users/me/profile', payload));
}

// ============================================================
// 隐私设置
// ============================================================

export function getSettings(): Promise<UserSettings> {
  return unwrap(http.get<ApiResponse<UserSettings>>('/api/v1/users/me/settings'));
}

/** 更新隐私设置。**部分更新语义**（API §3.14），只传要改的字段 */
export async function updateSettings(payload: UpdateSettingsPayload): Promise<void> {
  await unwrap<null>(http.patch<ApiResponse<null>>('/api/v1/users/me/settings', payload));
}

// ============================================================
// 注销账号
// ============================================================

export interface DeactivateAccountPayload {
  password: string;
  /** 必须为「注销」二字，后端也校验 */
  confirmation: string;
}

/**
 * 注销账号（API §3.19）。
 *
 * **不可逆**：账号软删除，会话/记忆/额度被清理，足迹匿名化保留。
 * 成功返回 204，前端需清本地状态并跳登录页。
 */
export async function deactivateAccount(
  payload: DeactivateAccountPayload,
): Promise<void> {
  await unwrap<null>(
    http.post<ApiResponse<null>>('/api/v1/users/me/deactivate', payload),
  );
}

// ============================================================
// 修改密码
// ============================================================

export async function changePassword(payload: {
  old_password?: string;
  new_password: string;
}): Promise<void> {
  await unwrap<null>(http.put<ApiResponse<null>>('/api/v1/users/me/password', payload));
}
