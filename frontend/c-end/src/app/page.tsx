/**
 * 首页（SSR）。
 *
 * 数据来源：M02 景点内容模块的推荐接口。
 * 基础工程阶段尚未实现业务接口，页面以空态占位，接口完成后接入。
 */
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '云游坊 - 智能旅行规划',
};

export default function HomePage() {
  return (
    <div className="page-container" style={{ paddingTop: 48 }}>
      <section style={{ textAlign: 'center', marginBottom: 64 }}>
        <h1 style={{ fontSize: 40, marginBottom: 16 }}>发现好去处，规划好旅程</h1>
        <p style={{ fontSize: 16, color: 'var(--color-text-secondary)' }}>
          AI 驱动的旅行推荐与行程规划，为每一次出发提供灵感与方案
        </p>
      </section>

      <section>
        <h2 style={{ fontSize: 24, marginBottom: 24 }}>为你推荐</h2>
        <div
          style={{
            border: '1px dashed var(--color-border)',
            borderRadius: 12,
            padding: '48px 24px',
            textAlign: 'center',
            color: 'var(--color-text-secondary)',
          }}
        >
          推荐内容接入中
        </div>
      </section>
    </div>
  );
}
