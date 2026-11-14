/**
 * M12 模型管理服务（API §10.1 ~ §10.11）。
 */
import { request } from '@/services/http';
import type { PageData } from '@/types/api';

export type ModelCategory = 'chat' | 'vision' | 'embedding' | 'rerank' | 'ocr';

export interface Model {
  id: string;
  name: string;
  category: ModelCategory;
  model_code: string;
  base_url: string;
  max_context_tokens: number | null;
  max_output_tokens: number | null;
  timeout_seconds: number;
  concurrency_limit: number | null;
  price_input: string | null;
  price_output: string | null;
  description: string | null;
  is_enabled: boolean;
  is_default: boolean;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  created_at: string;
  updated_at: string;
  /** 是否已配置 API Key。后端不回传密钥本身。 */
  has_api_key: boolean;
}

export interface ModelPayload {
  name: string;
  category: ModelCategory;
  model_code: string;
  base_url: string;
  /** 明文传入；不传保持原值，传空串清空（更新时） */
  api_key?: string | null;
  max_context_tokens?: number | null;
  max_output_tokens?: number | null;
  timeout_seconds?: number;
  concurrency_limit?: number | null;
  price_input?: string | null;
  price_output?: string | null;
  description?: string | null;
  is_default?: boolean;
}

export interface ModelCategoryOption {
  code: ModelCategory;
  name: string;
}

export function listModels(params: {
  category?: ModelCategory;
  is_enabled?: boolean;
  keyword?: string;
  page?: number;
  page_size?: number;
}): Promise<PageData<Model>> {
  return request({ url: '/models', params });
}

export function getModel(id: string): Promise<Model> {
  return request({ url: `/models/${id}` });
}

export function createModel(payload: ModelPayload): Promise<Model> {
  return request({ url: '/models', method: 'POST', data: payload });
}

export async function updateModel(id: string, payload: ModelPayload): Promise<void> {
  await request<null>({ url: `/models/${id}`, method: 'PUT', data: payload });
}

export async function setModelStatus(id: string, isEnabled: boolean): Promise<void> {
  await request<null>({
    url: `/models/${id}/status`,
    method: 'PATCH',
    data: { is_enabled: isEnabled },
  });
}

export async function setModelDefault(id: string): Promise<void> {
  await request<null>({ url: `/models/${id}/default`, method: 'PUT' });
}

export async function deleteModel(id: string): Promise<void> {
  await request<null>({ url: `/models/${id}`, method: 'DELETE' });
}

/** 类别是固定枚举，由后端返回，前端不硬编码中文名 */
export function listModelCategories(): Promise<{ items: ModelCategoryOption[] }> {
  return request({ url: '/models/categories' });
}
