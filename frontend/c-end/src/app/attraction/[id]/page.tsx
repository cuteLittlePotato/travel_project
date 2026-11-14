/**
 * 景点详情页（SSR，M02-T10）。
 *
 * 结构（原型 `prototype/c-end/attraction-detail.html`）：
 *   图集 → 标题 + 城市/分类 → 基本信息 → 图谱入口 →
 *   游览建议 → 快速操作 → 关联内容
 *
 * **未上架或不存在返回 404**（API §4.2 返回 12001）。
 */
import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';

import { DetailGallery } from '@/components/attraction/DetailGallery';
import { QuickActions } from '@/components/attraction/QuickActions';
import { RelatedContent } from '@/components/attraction/RelatedContent';
import { serverApi, type AttractionDetail } from '@/services/attraction';

interface PageProps {
  params: { id: string };
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  try {
    const detail = await serverApi.getAttraction(params.id);
    return {
      title: `${detail.name} - 云游坊`,
      description: detail.summary ?? undefined,
    };
  } catch {
    return { title: '景点不存在 - 云游坊' };
  }
}

/** 开放时间压缩成一行摘要 */
function formatOpeningHours(hours: AttractionDetail['opening_hours']): string {
  if (!hours) return '—';

  const days = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const;
  const values = days
    .map((d) => hours[d])
    .filter((v): v is string => typeof v === 'string' && v.length > 0);

  if (values.length === 0) return hours.note ?? '—';

  const first = values[0];
  const allSame =
    first !== undefined && values.length === 7 && values.every((v) => v === first);

  if (allSame && first !== undefined) {
    const main = first === 'closed' ? '全天闭馆' : first;
    return hours.note ? `${main}（${hours.note}）` : main;
  }

  return hours.note ? `按星期设置（${hours.note}）` : '按星期设置';
}

export default async function AttractionDetailPage({ params }: PageProps) {
  let detail: AttractionDetail;

  try {
    detail = await serverApi.getAttraction(params.id);
  } catch {
    // 不存在或未上架都走 404——不区分两者，避免探测
    notFound();
  }

  const {
    name,
    city,
    categories,
    image_urls,
    summary,
    description,
    address,
    ticket_price,
    opening_hours,
    visit_duration_minutes,
    best_seasons,
    website,
    phone,
    traffic_guide,
    popularity,
    transports,
    related,
  } = detail;

  return (
    <div className="page-container" style={{ paddingTop: 24, paddingBottom: 64 }}>
      {/* ---------- 面包屑 ---------- */}
      <nav style={{ fontSize: 13, marginBottom: 16, color: 'var(--color-text-secondary)' }}>
        <Link href="/" style={{ color: 'inherit' }}>
          首页
        </Link>
        {city && (
          <>
            <span style={{ margin: '0 6px' }}>/</span>
            <span>{city.province?.name ?? city.name}</span>
            <span style={{ margin: '0 6px' }}>/</span>
            <span>{city.name}</span>
          </>
        )}
      </nav>

      <DetailGallery name={name} imageUrls={image_urls} />

      {/* ---------- 标题区 ---------- */}
      <header style={{ margin: '24px 0' }}>
        <h1 style={{ fontSize: 32, marginBottom: 10 }}>{name}</h1>

        <div
          style={{
            display: 'flex',
            gap: 10,
            flexWrap: 'wrap',
            alignItems: 'center',
            fontSize: 14,
          }}
        >
          {city && <span>📍 {city.name}</span>}
          {categories.map((category) => (
            <span
              key={category.id}
              style={{
                background: '#f0f5ff',
                color: '#1677ff',
                padding: '2px 10px',
                borderRadius: 12,
                fontSize: 13,
              }}
            >
              {category.name}
            </span>
          ))}
          <span style={{ color: '#fa541c', fontWeight: 600 }}>
            🔥 {popularity.toFixed(1)}
          </span>
        </div>

        {summary && (
          <p
            style={{
              marginTop: 14,
              fontSize: 15,
              color: 'var(--color-text-secondary)',
              lineHeight: 1.7,
            }}
          >
            {summary}
          </p>
        )}
      </header>

      {/* ---------- 基本信息 ---------- */}
      <section style={cardStyle}>
        <h2 style={sectionTitleStyle}>📋 基本信息</h2>
        <dl
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
            gap: '16px 32px',
            margin: 0,
          }}
        >
          <InfoItem label="门票价格">
            {ticket_price ? `¥${Number(ticket_price).toFixed(2)}` : '免费'}
          </InfoItem>
          <InfoItem label="开放时间">{formatOpeningHours(opening_hours)}</InfoItem>
          <InfoItem label="建议游玩">
            {visit_duration_minutes
              ? `${Math.round(visit_duration_minutes / 60)} 小时`
              : '—'}
          </InfoItem>
          <InfoItem label="最佳季节">
            {best_seasons.length > 0 ? best_seasons.join('、') : '—'}
          </InfoItem>
          <InfoItem label="地址">{address ?? '—'}</InfoItem>
          <InfoItem label="电话">{phone ?? '—'}</InfoItem>
          {website && (
            <InfoItem label="官网">
              <a
                href={website}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: '#1677ff' }}
              >
                访问
              </a>
            </InfoItem>
          )}
        </dl>
      </section>

      {/* ---------- 详细介绍 ---------- */}
      {description && (
        <section style={cardStyle}>
          <h2 style={sectionTitleStyle}>📖 景点介绍</h2>
          {/* 富文本由运营录入，后端已做存储；此处按 HTML 渲染 */}
          <div
            style={{ fontSize: 15, lineHeight: 1.8 }}
            dangerouslySetInnerHTML={{ __html: description }}
          />
        </section>
      )}

      {/* ---------- 交通指南 ---------- */}
      {(traffic_guide || transports.length > 0) && (
        <section style={cardStyle}>
          <h2 style={sectionTitleStyle}>🚌 交通指南</h2>

          {traffic_guide && (
            <p style={{ fontSize: 15, lineHeight: 1.8, marginBottom: 16 }}>
              {traffic_guide}
            </p>
          )}

          {transports.length > 0 && (
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {transports.map((transport) => (
                <li key={transport.id} style={{ fontSize: 14, lineHeight: 1.9 }}>
                  <span style={{ fontWeight: 500 }}>{transport.name}</span>
                  {transport.transport_type && (
                    <span style={{ color: 'var(--color-text-secondary)', marginLeft: 8 }}>
                      {transport.transport_type}
                    </span>
                  )}
                  {transport.price && (
                    <span style={{ color: '#fa541c', marginLeft: 8 }}>
                      ¥{Number(transport.price).toFixed(2)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* ---------- 快速操作 ---------- */}
      <section style={cardStyle}>
        <h2 style={sectionTitleStyle}>🎯 快速操作</h2>
        <QuickActions
          attractionId={detail.id}
          attractionName={name}
          isLoggedIn={false}
        />
      </section>

      {/* ---------- 关联内容 ---------- */}
      <section style={{ marginTop: 24 }}>
        <h2 style={{ ...sectionTitleStyle, marginBottom: 16 }}>🔗 关联内容</h2>
        <RelatedContent related={related} />
      </section>
    </div>
  );
}

const cardStyle: React.CSSProperties = {
  background: '#fff',
  border: '1px solid var(--color-border)',
  borderRadius: 12,
  padding: 24,
  marginTop: 20,
};

const sectionTitleStyle: React.CSSProperties = {
  fontSize: 18,
  marginTop: 0,
  marginBottom: 16,
};

function InfoItem({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <dt
        style={{
          fontSize: 13,
          color: 'var(--color-text-secondary)',
          marginBottom: 4,
        }}
      >
        {label}
      </dt>
      <dd style={{ margin: 0, fontSize: 15 }}>{children}</dd>
    </div>
  );
}
