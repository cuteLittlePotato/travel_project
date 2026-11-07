/**
 * 个人中心 - 个人中心（CSR，需登录，M01）
 */
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '个人中心',
};

export default function ProfilePage() {
  return (
    <div className="page-container" style={{ paddingTop: 32 }}>
      <h1 style={{ fontSize: 24, marginBottom: 16 }}>个人中心</h1>
      <div
        style={{
          border: '1px dashed var(--color-border)',
          borderRadius: 12,
          padding: '48px 24px',
          textAlign: 'center',
          color: 'var(--color-text-secondary)',
        }}
      >
        个人中心内容接入中
      </div>
    </div>
  );
}
