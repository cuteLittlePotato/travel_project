'use client';

/**
 * C 端顶部导航。
 *
 * SSR 首屏不查询登录态（评审 §Q1），因此导航栏在客户端 hydration 后才显示
 * 用户相关入口，首屏始终可静态渲染。
 */
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useState } from 'react';
import { Avatar, Button, Dropdown, Modal, Space, Typography } from 'antd';
import { LogoutOutlined, UserOutlined } from '@ant-design/icons';
import type { MenuProps } from 'antd';

import { NotificationBell } from '@/components/notification/NotificationBell';
import { useLogout } from '@/hooks/useLogout';
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
  const router = useRouter();
  const { user, accessToken } = useAuthStore();
  const [logoutConfirmOpen, setLogoutConfirmOpen] = useState(false);
  const handleLogout = useLogout();

  /** 头像下拉：个人中心 + 退出登录 */
  const accountMenuItems: MenuProps['items'] = [
    {
      key: 'header',
      // 下拉顶部显示当前账号，便于多账号场景确认「我是谁」
      label: (
        <div style={{ padding: '4px 0', cursor: 'default' }}>
          <Typography.Text strong>
            {user?.nickname ?? '已登录用户'}
          </Typography.Text>
        </div>
      ),
      disabled: true,
    },
    { type: 'divider' },
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: '个人中心',
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      danger: true,
    },
  ];

  const onAccountMenuClick: MenuProps['onClick'] = ({ key }) => {
    if (key === 'profile') {
      router.push('/profile');
      return;
    }

    if (key === 'logout') {
      setLogoutConfirmOpen(true);
    }
  };

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
          <>
            <NotificationBell />
            <Dropdown
              menu={{ items: accountMenuItems, onClick: onAccountMenuClick }}
              trigger={['click']}
              placement="bottomRight"
            >
              <button
                type="button"
                aria-label="账号菜单"
                style={{
                  border: 'none',
                  background: 'none',
                  padding: 0,
                  cursor: 'pointer',
                  lineHeight: 0,
                }}
              >
                <Avatar
                  src={user?.avatar_url ?? undefined}
                  icon={<UserOutlined />}
                  style={{ cursor: 'pointer' }}
                />
              </button>
            </Dropdown>
          </>
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

      {/* 退出确认：用受控 Modal 而非 modal.confirm，
          便于测试断言，也避免命令式 API 与 React 状态脱节 */}
      <Modal
        open={logoutConfirmOpen}
        title="确定要退出登录吗？"
        onCancel={() => setLogoutConfirmOpen(false)}
        onOk={async () => {
          setLogoutConfirmOpen(false);
          await handleLogout();
        }}
        okText="退出"
        cancelText="取消"
        okButtonProps={{ danger: true }}
      >
        退出后需要重新登录，所有设备都会退出。
      </Modal>
    </header>
  );
}
