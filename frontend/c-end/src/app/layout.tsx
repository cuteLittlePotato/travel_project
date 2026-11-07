import type { Metadata } from 'next';
import { AntdRegistry } from '@ant-design/nextjs-registry';

import { AppProviders } from '@/lib/api/providers';
import { AuthBootstrap } from '@/components/layout/AuthBootstrap';
import { SiteFooter } from '@/components/layout/SiteFooter';
import { SiteHeader } from '@/components/layout/SiteHeader';
import '@/styles/globals.css';

export const metadata: Metadata = {
  title: {
    default: '云游坊 - 智能旅行规划',
    template: '%s | 云游坊',
  },
  description: '云游坊：AI 驱动的旅行推荐与行程规划平台，发现好去处，规划好旅程。',
  keywords: ['旅游', '旅行规划', '景点推荐', '行程规划', 'AI 导游'],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        {/* AntdRegistry 负责 App Router 下的样式注入，避免首屏样式闪烁 */}
        <AntdRegistry>
          <AppProviders>
            <AuthBootstrap />
            <SiteHeader />
            <main style={{ minHeight: 'calc(100vh - 64px - 200px)' }}>{children}</main>
            <SiteFooter />
          </AppProviders>
        </AntdRegistry>
      </body>
    </html>
  );
}
