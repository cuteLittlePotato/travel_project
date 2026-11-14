/**
 * 景点分类的展示常量（M11-T14）。
 *
 * 单独成文件，避免 `index.tsx` ↔ `CategoryModal.tsx` 互相 import。
 */
export type CategoryType = 'theme' | 'level';

export const CATEGORY_TYPE_LABEL: Record<CategoryType, string> = {
  theme: '主题分类',
  level: '等级分类',
};

export const CATEGORY_TYPE_HINT: Record<CategoryType, string> = {
  theme: '按内容主题划分，C 端景点筛选的主要维度',
  level: '按景区评级划分，如 5A、4A',
};
