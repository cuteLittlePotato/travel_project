'use client';

/**
 * 第三方登录按钮组（API §3.5）。
 *
 * 流程：
 *   1. 前端生成 state 存入 sessionStorage
 *   2. 跳转第三方授权页（当前未对接，按钮提示「暂未开放」）
 *   3. 回调页面校验 state 后调 oauthLogin
 *
 * **state 由前端校验**（2026-11-08 确认）：后端无状态，
 * 只接收回调结果，真实性由前端比对。
 */
import { useState } from 'react';
import { Button, Space, Tooltip } from 'antd';
import {
  AlipayCircleFilled,
  WechatFilled,
  WeiboCircleFilled,
} from '@ant-design/icons';

import type { OAuthProvider } from '@/services/auth';

/** 生成防 CSRF 的 state 并存入 sessionStorage */
export function createOAuthState(): string {
  const state = `${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
  if (typeof window !== 'undefined') {
    sessionStorage.setItem('oauth_state', state);
  }
  return state;
}

/** 校验回调的 state 是否匹配 */
export function verifyOAuthState(received: string): boolean {
  if (typeof window === 'undefined') return false;
  const saved = sessionStorage.getItem('oauth_state');
  sessionStorage.removeItem('oauth_state');
  return Boolean(saved) && saved === received;
}

interface ProviderConfig {
  key: OAuthProvider;
  label: string;
  icon: React.ReactNode;
  color: string;
}

const PROVIDERS: ProviderConfig[] = [
  { key: 'wechat', label: '微信', icon: <WechatFilled />, color: '#07c160' },
  { key: 'alipay', label: '支付宝', icon: <AlipayCircleFilled />, color: '#1677ff' },
  { key: 'weibo', label: '微博', icon: <WeiboCircleFilled />, color: '#e6162d' },
];

export interface OAuthButtonsProps {
  /** 点击第三方按钮。默认行为是提示未开放 */
  onSelect?: (provider: OAuthProvider) => void;
  /** 是否已配置（未配置时提示「暂未开放」） */
  enabled?: boolean;
}

export function OAuthButtons({ onSelect, enabled = false }: OAuthButtonsProps) {
  const [hovered, setHovered] = useState<OAuthProvider | null>(null);

  return (
    <Space size={16} style={{ width: '100%', justifyContent: 'center' }}>
      {PROVIDERS.map((provider) => {
        const button = (
          <Button
            key={provider.key}
            shape="circle"
            size="large"
            icon={provider.icon}
            aria-label={`${provider.label}登录`}
            style={{
              color: enabled ? provider.color : '#bfbfbf',
              borderColor: hovered === provider.key ? provider.color : undefined,
            }}
            onMouseEnter={() => setHovered(provider.key)}
            onMouseLeave={() => setHovered(null)}
            onClick={() => onSelect?.(provider.key)}
          />
        );

        return enabled ? (
          button
        ) : (
          <Tooltip key={provider.key} title={`${provider.label}登录暂未开放`}>
            {button}
          </Tooltip>
        );
      })}
    </Space>
  );
}
