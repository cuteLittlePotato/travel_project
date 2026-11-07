/**
 * 我的计划 - 我的计划（CSR，需登录，M04）
 */
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '我的计划',
};

export default function PlansPage() {
  return (
    <div className="page-container" style={{ paddingTop: 32 }}>
      <h1 style={{ fontSize: 24, marginBottom: 16 }}>我的计划</h1>
      <div
        style={{
          border: '1px dashed var(--color-border)',
          borderRadius: 12,
          padding: '48px 24px',
          textAlign: 'center',
          color: 'var(--color-text-secondary)',
        }}
      >
        我的计划内容接入中
      </div>
    </div>
  );
}
