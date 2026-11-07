/**
 * 智能规划 - 智能对话（CSR，需登录，M03）
 */
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '智能规划',
};

export default function ChatPage() {
  return (
    <div className="page-container" style={{ paddingTop: 32 }}>
      <h1 style={{ fontSize: 24, marginBottom: 16 }}>智能规划</h1>
      <div
        style={{
          border: '1px dashed var(--color-border)',
          borderRadius: 12,
          padding: '48px 24px',
          textAlign: 'center',
          color: 'var(--color-text-secondary)',
        }}
      >
        智能规划内容接入中
      </div>
    </div>
  );
}
