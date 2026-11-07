/**
 * 景点详情 - SSR，M02
 */
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '景点详情',
};

export default async function AttractionDetailPage({ params }: { params: { id: string } }) {
  return (
    <div className="page-container" style={{ paddingTop: 32 }}>
      <h1 style={{ fontSize: 24, marginBottom: 16 }}>景点详情</h1>
      <p style={{ color: 'var(--color-text-secondary)' }}>ID: {params.id}</p>
      <div
        style={{
          border: '1px dashed var(--color-border)',
          borderRadius: 12,
          padding: '48px 24px',
          textAlign: 'center',
          color: 'var(--color-text-secondary)',
        }}
      >
        景点详情内容接入中
      </div>
    </div>
  );
}
