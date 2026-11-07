/**
 * 我的足迹 - 我的足迹（CSR，需登录，M05）
 */
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '我的足迹',
};

export default function FootprintsPage() {
  return (
    <div className="page-container" style={{ paddingTop: 32 }}>
      <h1 style={{ fontSize: 24, marginBottom: 16 }}>我的足迹</h1>
      <div
        style={{
          border: '1px dashed var(--color-border)',
          borderRadius: 12,
          padding: '48px 24px',
          textAlign: 'center',
          color: 'var(--color-text-secondary)',
        }}
      >
        我的足迹内容接入中
      </div>
    </div>
  );
}
