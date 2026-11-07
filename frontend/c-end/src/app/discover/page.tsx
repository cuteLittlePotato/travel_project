/**
 * 发现 - 发现页（SSR，M02）
 */
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '发现',
};

export default function DiscoverPage() {
  return (
    <div className="page-container" style={{ paddingTop: 32 }}>
      <h1 style={{ fontSize: 24, marginBottom: 16 }}>发现</h1>
      <div
        style={{
          border: '1px dashed var(--color-border)',
          borderRadius: 12,
          padding: '48px 24px',
          textAlign: 'center',
          color: 'var(--color-text-secondary)',
        }}
      >
        发现内容接入中
      </div>
    </div>
  );
}
