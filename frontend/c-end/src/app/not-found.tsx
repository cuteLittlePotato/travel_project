/**
 * 全局 404 页面。
 *
 * 景点详情在「不存在」与「未上架」时都调用 `notFound()`，
 * 由本页面统一兜底——两者对用户是同一件事：这个页面没有了。
 */
import Link from 'next/link';

export default function NotFound() {
  return (
    <div
      className="page-container"
      style={{
        minHeight: '60vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        paddingTop: 80,
        paddingBottom: 80,
      }}
    >
      <div style={{ fontSize: 72, marginBottom: 16 }}>🧭</div>

      <h1 style={{ fontSize: 28, marginBottom: 10 }}>这个页面走丢了</h1>

      <p
        style={{
          fontSize: 15,
          color: 'var(--color-text-secondary)',
          marginBottom: 28,
          maxWidth: 420,
          lineHeight: 1.7,
        }}
      >
        景点可能已下架，或者链接不正确。回到首页看看别的目的地吧。
      </p>

      <div style={{ display: 'flex', gap: 12 }}>
        <Link
          href="/"
          style={{
            padding: '10px 28px',
            borderRadius: 8,
            background: '#1677ff',
            color: '#fff',
            textDecoration: 'none',
            fontSize: 15,
          }}
        >
          返回首页
        </Link>
        <Link
          href="/discover"
          style={{
            padding: '10px 28px',
            borderRadius: 8,
            border: '1px solid var(--color-border)',
            color: 'inherit',
            textDecoration: 'none',
            fontSize: 15,
          }}
        >
          去发现页
        </Link>
      </div>
    </div>
  );
}
