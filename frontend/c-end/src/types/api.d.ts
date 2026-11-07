/**
 * 后端统一响应结构的 TypeScript 类型。
 *
 * 注意：本文件为手工维护的基础类型；接口级类型由 `npm run gen:api`
 * 从后端 OpenAPI schema 生成到 `api-generated.d.ts`，不要手工编辑生成产物。
 */

/** 统一响应外壳 */
export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T | null;
}

/** 分页响应体 */
export interface PageData<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

/** 分页查询参数 */
export interface PageQuery {
  page?: number;
  page_size?: number;
}

/** 通用查询参数 */
export interface CommonQuery extends PageQuery {
  keyword?: string;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
}

/** 参数校验失败的字段级详情 */
export interface ValidationErrorItem {
  field: string;
  reason: string;
}

/** 业务错误码（与后端 app/core/exceptions.py 保持一致） */
export const ErrorCode = {
  SUCCESS: 0,
  VALIDATION_FAILED: 10001,
  INTERNAL_ERROR: 10002,
  RATE_LIMITED: 10003,
  NOT_FOUND: 10004,
  UNAUTHORIZED: 11001,
  ACCOUNT_BANNED: 11002,
  PERMISSION_DENIED: 25001,
} as const;

export type ErrorCodeValue = (typeof ErrorCode)[keyof typeof ErrorCode];
