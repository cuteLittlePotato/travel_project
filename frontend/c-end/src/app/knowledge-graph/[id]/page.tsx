/**
 * 景点知识图谱 - SSR，M10
 */
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '景点知识图谱',
};

export default async function KnowledgeGraphPage({ params }: { params: { id: string } }) {
  return (
    <div className="page-container" style={{ paddingTop: 32 }}>
      <h1 style={{ fontSize: 24, marginBottom: 16 }}>景点知识图谱</h1>
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
        景点知识图谱内容接入中
      </div>
    </div>
  );
}
