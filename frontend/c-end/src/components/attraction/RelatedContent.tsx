/**
 * 关联内容卡片（人物 / 事件 / 文化 / 周边景点）。
 *
 * 数据来自 M10 知识图谱。**M10 尚未开发**，当前各数组为空——
 * 组件按空态处理，不会因为没数据而报错或留空白区块。
 */
import Link from 'next/link';

import type { AttractionDetail } from '@/services/attraction';

type Related = AttractionDetail['related'];

export interface RelatedContentProps {
  related: Related;
}

/** 四个板块的配置：标题 + 取数据的函数 + 渲染单行的函数 */
const SECTIONS = [
  {
    key: 'persons' as const,
    title: '相关人物',
    icon: '👤',
    render: (item: Related['persons'][number]) => (
      <>
        <span style={{ fontWeight: 500 }}>{item.name}</span>
        {item.dynasty && (
          <span style={{ color: 'var(--color-text-secondary)', marginLeft: 6 }}>
            {item.dynasty}
          </span>
        )}
        <span style={{ color: 'var(--color-text-secondary)', marginLeft: 6 }}>
          · {item.relation}
        </span>
      </>
    ),
  },
  {
    key: 'events' as const,
    title: '历史事件',
    icon: '📜',
    render: (item: Related['events'][number]) => (
      <>
        <span style={{ fontWeight: 500 }}>{item.name}</span>
        {item.event_time && (
          <span style={{ color: 'var(--color-text-secondary)', marginLeft: 6 }}>
            {item.event_time}
          </span>
        )}
      </>
    ),
  },
  {
    key: 'cultures' as const,
    title: '相关文化',
    icon: '🎭',
    render: (item: Related['cultures'][number]) => (
      <>
        <span style={{ fontWeight: 500 }}>{item.name}</span>
        {item.culture_type && (
          <span style={{ color: 'var(--color-text-secondary)', marginLeft: 6 }}>
            · {item.culture_type}
          </span>
        )}
      </>
    ),
  },
  {
    key: 'nearby_attractions' as const,
    title: '周边景点',
    icon: '🗺️',
    render: (item: Related['nearby_attractions'][number]) => (
      <Link
        href={`/attraction/${item.id}`}
        style={{ color: '#1677ff', textDecoration: 'none' }}
      >
        {item.name}
        <span style={{ color: 'var(--color-text-secondary)', marginLeft: 6 }}>
          {item.distance_km} km
        </span>
      </Link>
    ),
  },
];

export function RelatedContent({ related }: RelatedContentProps) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
        gap: 16,
      }}
    >
      {SECTIONS.map((section) => {
        const items = related[section.key] as Array<{ id: string }>;

        return (
          <section
            key={section.key}
            style={{
              border: '1px solid var(--color-border)',
              borderRadius: 10,
              padding: 16,
              background: '#fff',
            }}
          >
            <h3
              style={{
                margin: '0 0 12px',
                fontSize: 15,
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <span>{section.icon}</span>
              {section.title}
            </h3>

            {items.length === 0 ? (
              <p
                style={{
                  margin: 0,
                  fontSize: 13,
                  color: 'var(--color-text-secondary)',
                }}
              >
                暂无数据
              </p>
            ) : (
              <ul style={{ margin: 0, padding: 0, listStyle: 'none' }}>
                {items.map((item) => (
                  <li
                    key={item.id}
                    style={{ fontSize: 14, padding: '6px 0', lineHeight: 1.6 }}
                  >
                    {/* 各类数据的渲染函数不同，类型在此处已收窄 */}
                    {(
                      section.render as (value: unknown) => React.ReactNode
                    )(item)}
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}
