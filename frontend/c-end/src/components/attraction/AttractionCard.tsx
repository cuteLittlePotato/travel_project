/**
 * 景点卡片（首页 / 列表页共用）。
 *
 * 图片加载失败降级为渐变背景（DoD 边界）——景点图片多来自外部图床，
 * 失效是常态，不能因此让整张卡片塌掉。
 */
import Link from 'next/link';

import type { AttractionListItem } from '@/services/attraction';

export interface AttractionCardProps {
  attraction: AttractionListItem;
  /** 是否展示热度标记（排行榜用） */
  showRank?: number;
}

/** 图片加载失败时按景点名生成稳定的渐变——同一景点每次颜色一致 */
function gradientFor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) {
    hash = (hash * 31 + name.charCodeAt(i)) % 360;
  }
  return `linear-gradient(135deg, hsl(${hash}, 70%, 75%), hsl(${(hash + 40) % 360}, 70%, 65%))`;
}

export function AttractionCard({ attraction, showRank }: AttractionCardProps) {
  const { id, name, image_url, summary, city, categories, ticket_price, popularity } =
    attraction;

  return (
    <Link
      href={`/attraction/${id}`}
      style={{ display: 'block', color: 'inherit', textDecoration: 'none' }}
    >
      <article
        style={{
          border: '1px solid var(--color-border)',
          borderRadius: 12,
          overflow: 'hidden',
          background: '#fff',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          transition: 'box-shadow 0.2s, transform 0.2s',
        }}
        className="attraction-card"
      >
        <div style={{ position: 'relative', aspectRatio: '4 / 3' }}>
          {image_url ? (
            // 外部图床域名不固定，next/image 需要逐个配置 remotePatterns，
            // 这里按需用原生 img。改用 next/image 时可加 unoptimized。
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={image_url}
              alt={name}
              style={{ width: '100%', height: '100%', objectFit: 'cover' }}
            />
          ) : (
            <div
              style={{
                width: '100%',
                height: '100%',
                background: gradientFor(name),
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
                fontSize: 28,
                fontWeight: 600,
                opacity: 0.9,
              }}
            >
              {name.slice(0, 2)}
            </div>
          )}

          {showRank !== undefined && (
            <span
              style={{
                position: 'absolute',
                top: 8,
                left: 8,
                background: showRank <= 3 ? '#fa541c' : 'rgba(0,0,0,0.55)',
                color: '#fff',
                borderRadius: 12,
                padding: '2px 10px',
                fontSize: 12,
                fontWeight: 600,
              }}
            >
              {showRank}
            </span>
          )}
        </div>

        <div style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>{name}</h3>

          <div style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>
            {city?.name ?? '—'}
            {categories.length > 0 && ` · ${categories.map((c) => c.name).join(' / ')}`}
          </div>

          {summary && (
            <p
              style={{
                margin: 0,
                fontSize: 13,
                color: 'var(--color-text-secondary)',
                display: '-webkit-box',
                WebkitLineClamp: 2,
                WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
              }}
            >
              {summary}
            </p>
          )}

          <div
            style={{
              marginTop: 'auto',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              paddingTop: 8,
            }}
          >
            <span style={{ color: '#fa541c', fontWeight: 600 }}>
              {ticket_price ? `¥${Number(ticket_price).toFixed(0)}` : '免费'}
            </span>

            {/* DoD：热度值 hover 显示 recommend_reason。
                M17 未开发，recommend_reason 恒为 null，此时不显示 tooltip */}
            <span
              title={attraction.recommend_reason ?? undefined}
              style={{
                fontSize: 13,
                color: 'var(--color-text-secondary)',
                cursor: attraction.recommend_reason ? 'help' : 'default',
                borderBottom: attraction.recommend_reason
                  ? '1px dashed currentColor'
                  : 'none',
              }}
            >
              🔥 {popularity.toFixed(1)}
            </span>
          </div>
        </div>
      </article>
    </Link>
  );
}
