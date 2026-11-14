'use client';

/**
 * 分类标签（首页筛选器）。
 *
 * 主题分类与等级分类混排展示——用户不关心「theme / level」的区分，
 * 他们只想按「历史人文」「5A景区」筛选。
 */
import type { CategoryGrouped } from '@/services/attraction';

export interface CategoryTabsProps {
  categories: CategoryGrouped;
  /** 当前选中的分类 ID，null 表示「全部」 */
  selectedId: string | null;
  onChange: (categoryId: string | null) => void;
}

export function CategoryTabs({ categories, selectedId, onChange }: CategoryTabsProps) {
  const all = [...categories.themes, ...categories.levels];

  if (all.length === 0) return null;

  return (
    <div
      style={{
        display: 'flex',
        gap: 8,
        flexWrap: 'wrap',
        marginBottom: 16,
      }}
    >
      <TabButton active={selectedId === null} onClick={() => onChange(null)}>
        全部
      </TabButton>

      {all.map((category) => (
        <TabButton
          key={category.id}
          active={selectedId === category.id}
          onClick={() => onChange(category.id)}
        >
          {category.name}
        </TabButton>
      ))}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      style={{
        padding: '6px 16px',
        borderRadius: 16,
        border: `1px solid ${active ? '#1677ff' : 'var(--color-border)'}`,
        background: active ? '#1677ff' : '#fff',
        color: active ? '#fff' : 'inherit',
        fontSize: 14,
        cursor: 'pointer',
        transition: 'all 0.2s',
      }}
    >
      {children}
    </button>
  );
}
