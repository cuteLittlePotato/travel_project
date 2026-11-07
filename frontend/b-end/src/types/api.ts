/**
 * 后端统一响应结构的 TypeScript 类型。
 *
 * 接口级类型由 `npm run gen:api` 从后端 OpenAPI schema 生成到
 * `api-generated.d.ts`，本文件只维护跨接口通用结构。
 */

export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T | null;
}

export interface PageData<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface PageQuery {
  page?: number;
  page_size?: number;
}

export interface CommonQuery extends PageQuery {
  keyword?: string;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
}

export interface ValidationErrorItem {
  field: string;
  reason: string;
}

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
