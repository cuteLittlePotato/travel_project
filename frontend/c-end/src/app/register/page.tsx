/**
 * 注册 - 注册页（M01-T16）
 */
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '注册',
};

export default function RegisterPage() {
  return (
    <div className="page-container" style={{ paddingTop: 32 }}>
      <h1 style={{ fontSize: 24, marginBottom: 16 }}>注册</h1>
      <div
        style={{
          border: '1px dashed var(--color-border)',
          borderRadius: 12,
          padding: '48px 24px',
          textAlign: 'center',
          color: 'var(--color-text-secondary)',
        }}
      >
        注册内容接入中
      </div>
    </div>
  );
}
