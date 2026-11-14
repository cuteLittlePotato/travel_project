/**
 * 模型类别的展示元数据（M12-T09）。
 *
 * 中文名取自后端 `GET /models/categories`（固定枚举，评审 §Q6），
 * 这里只维护**图标与配色**——那是纯前端展示决策，不该占后端字段。
 */
import type { ModelCategory } from '@/services/model';

export interface CategoryMeta {
  icon: string;
  /** Ant Design Tag 的 color，与原型配色对应 */
  color: string;
}

export const CATEGORY_META: Record<ModelCategory, CategoryMeta> = {
  chat: { icon: '💬', color: 'purple' },
  vision: { icon: '🖼️', color: 'magenta' },
  embedding: { icon: '🔢', color: 'blue' },
  rerank: { icon: '📊', color: 'green' },
  ocr: { icon: '📄', color: 'orange' },
};

/** 「全部」标签页的 key */
export const ALL_CATEGORY = 'all' as const;
export type CategoryFilter = ModelCategory | typeof ALL_CATEGORY;
