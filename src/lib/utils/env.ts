/**
 * 环境变量访问集中入口，避免各处散落 process.env 读取。
 */
export const env = {
  /** 浏览器侧 API 前缀；留空表示同源 */
  apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? '',
  /** SSR 时服务端访问后端的地址 */
  internalBaseUrl: process.env.API_INTERNAL_BASE_URL ?? 'http://127.0.0.1:8000',
} as const;
