export function SiteFooter() {
  return (
    <footer
      style={{
        borderTop: '1px solid #f0f0f0',
        padding: '32px 0',
        marginTop: 64,
        textAlign: 'center',
        color: '#8c8c8c',
        fontSize: 13,
      }}
    >
      <div style={{ marginBottom: 8 }}>云游坊 · 智能旅行规划</div>
      <div>© {new Date().getFullYear()} 云游坊 版权所有</div>
    </footer>
  );
}
