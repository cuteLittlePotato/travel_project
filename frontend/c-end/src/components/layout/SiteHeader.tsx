'use client';

/**
 * C 端顶部导航。
 *
 * SSR 首屏不查询登录态（评审 §Q1），因此导航栏在客户端 hydration 后才显示
 * 用户相关入口，首屏始终可静态渲染。
 */
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Avatar, Button, Space } from 'antd';
import { UserOutlined } from '@ant-design/icons';

import { useAuthStore } from '@/stores/auth';

const NAV_ITEMS = [
  { href: '/', label: '首页' },
  { href: '/discover', label: '发现' },
  { href: '/chat', label: '智能规划' },
  { href: '/plans', label: '我的计划' },
  { href: '/footprints', label: '我的足迹' },
];

export function SiteHeader() {
  const pathname = usePathname();
  const { user, accessToken } = useAuthStore();

  return (
    <header
      style={{
        height: 64,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 32px',
        borderBottom: '1px solid #f0f0f0',
        background: '#fff',
        position: 'sticky',
        top: 0,
        zIndex: 100,
      }}
    >
      <Link href="/" style={{ fontSize: 20, fontWeight: 600, color: '#1677ff' }}>
        云游坊
      </Link>

      <nav style={{ display: 'flex', gap: 28 }}>
        {NAV_ITEMS.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              style={{
                color: active ? '#1677ff' : '#595959',
                fontWeight: active ? 600 : 400,
              }}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      <Space size={12}>
        {accessToken ? (
          <Link href="/profile">
            <Avatar src={user?.avatar_url ?? undefined} icon={<UserOutlined />} />
          </Link>
        ) : (
          <>
            <Link href="/login">
              <Button type="text">登录</Button>
            </Link>
            <Link href="/register">
              <Button type="primary">注册</Button>
            </Link>
          </>
        )}
      </Space>
    </header>
  );
}
