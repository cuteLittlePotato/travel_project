/**
 * 登录页（CSR）。
 *
 * Token 策略（评审 §Q1）：Access Token 存内存、Refresh Token 存 httpOnly Cookie。
 * 后端认证接口在 M01 任务中实现，当前保留表单骨架。
 */
'use client';

import { useState } from 'react';
import Link from 'next/link';
import { App, Button, Card, Form, Input, Segmented, Typography } from 'antd';

import { http, parseApiError } from '@/lib/api/http';
import { useAuthStore, type AuthUser } from '@/stores/auth';

type LoginMode = '密码登录' | '验证码登录';

interface LoginForm {
  account: string;
  password?: string;
  code?: string;
}

interface LoginResult {
  access_token: string;
  user: AuthUser;
}

export default function LoginPage() {
  const { message } = App.useApp();
  const [mode, setMode] = useState<LoginMode>('密码登录');
  const [loading, setLoading] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const setSession = useAuthStore((state) => state.setSession);

  const startCountdown = () => {
    setCountdown(60);
    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  const handleSubmit = async (values: LoginForm) => {
    setLoading(true);
    try {
      const url = mode === '密码登录' ? '/api/v1/auth/login' : '/api/v1/auth/login-by-code';
      const { data } = await http.post<{ code: number; message: string; data: LoginResult }>(
        url,
        values,
      );
      setSession(data.data.access_token, data.data.user);
      message.success('登录成功');
      window.location.href = '/';
    } catch (error) {
      message.error(parseApiError(error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="page-container"
      style={{ display: 'flex', justifyContent: 'center', paddingTop: 80 }}
    >
      <Card style={{ width: 400 }}>
        <Typography.Title level={3} style={{ textAlign: 'center' }}>
          登录云游坊
        </Typography.Title>

        <Segmented
          block
          options={['密码登录', '验证码登录']}
          value={mode}
          onChange={(value) => setMode(value as LoginMode)}
          style={{ marginBottom: 24 }}
        />

        <Form<LoginForm> layout="vertical" onFinish={handleSubmit} requiredMark={false}>
          <Form.Item
            name="account"
            label={mode === '密码登录' ? '手机号 / 邮箱 / 用户名' : '手机号 / 邮箱'}
            rules={[{ required: true, message: '请输入账号' }]}
          >
            <Input placeholder="请输入账号" size="large" autoComplete="username" />
          </Form.Item>

          {mode === '密码登录' ? (
            <Form.Item
              name="password"
              label="密码"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password placeholder="请输入密码" size="large" autoComplete="current-password" />
            </Form.Item>
          ) : (
            <Form.Item label="验证码" required>
              <div style={{ display: 'flex', gap: 8 }}>
                <Form.Item name="code" noStyle rules={[{ required: true, message: '请输入验证码' }]}>
                  <Input placeholder="请输入验证码" size="large" />
                </Form.Item>
                <Button size="large" disabled={countdown > 0} onClick={startCountdown}>
                  {countdown > 0 ? `${countdown}s` : '获取验证码'}
                </Button>
              </div>
            </Form.Item>
          )}

          <Button type="primary" htmlType="submit" block size="large" loading={loading}>
            登录
          </Button>
        </Form>

        <div style={{ marginTop: 16, textAlign: 'center' }}>
          <Link href="/register" style={{ color: '#1677ff' }}>
            还没有账号？立即注册
          </Link>
        </div>
      </Card>
    </div>
  );
}
