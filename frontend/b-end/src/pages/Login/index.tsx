/**
 * B 端管理员登录页（M15-T09，API §14.14）。
 *
 * Token 策略（评审 §Q1）：
 *   - Access Token 存内存（Zustand），页面刷新即丢失
 *   - Refresh Token 在 httpOnly Cookie 里，JS 读不到
 *   - 因此「刷新页面后仍是登录状态」靠的是启动时用 Cookie 换新 Token，
 *     而不是把 Token 存 localStorage
 *
 * 登录后跳转：优先回到 `?redirect=` 指定的页面（被 RequireAdmin 拦下时写入），
 * 否则进 /dashboard。
 */
import { useEffect, useState } from 'react';
import { App, Button, Card, Form, Input, Typography } from 'antd';
import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';

import { login } from '@/services/auth';
import { useAdminAuthStore } from '@/stores/auth';

interface LoginForm {
  username: string;
  password: string;
}

/** 避免开放重定向：只接受站内相对路径 */
function safeRedirect(target: string | null): string {
  if (!target) return '/dashboard';
  if (!target.startsWith('/') || target.startsWith('//')) return '/dashboard';
  if (target.startsWith('/login')) return '/dashboard';
  return target;
}

export function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { message } = App.useApp();
  const setSession = useAdminAuthStore((state) => state.setSession);
  const isAuthenticated = useAdminAuthStore((state) => state.isAuthenticated());

  const [submitting, setSubmitting] = useState(false);

  const redirectTo = safeRedirect(searchParams.get('redirect'));

  // 已登录直接跳走，避免停在登录页
  useEffect(() => {
    if (isAuthenticated) {
      navigate(redirectTo, { replace: true });
    }
  }, [isAuthenticated, navigate, redirectTo]);

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: (result) => {
      setSession(result.access_token, result.admin);
      message.success(`欢迎回来，${result.admin.real_name ?? result.admin.username}`);
      navigate(redirectTo, { replace: true });
    },
    // 11006 用户名或密码错误 / 11002 账号已禁用，后端已给出可读文案
    onError: (error: Error) => message.error(error.message || '登录失败'),
  });

  const handleSubmit = async (values: LoginForm) => {
    setSubmitting(true);
    try {
      await loginMutation.mutateAsync(values);
    } catch {
      // 错误提示已在 onError 处理
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #f5f7fa 0%, #e8eef7 100%)',
      }}
    >
      <Card style={{ width: 400, boxShadow: '0 8px 32px rgba(0,0,0,0.08)' }}>
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            云游坊运营后台
          </Typography.Title>
          <Typography.Text type="secondary">请使用管理员账号登录</Typography.Text>
        </div>

        <Form<LoginForm>
          layout="vertical"
          onFinish={handleSubmit}
          requiredMark={false}
          size="large"
        >
          <Form.Item
            name="username"
            label="账号"
            rules={[
              { required: true, message: '请输入账号' },
              { min: 3, max: 50, message: '账号长度为 3-50 字符' },
            ]}
          >
            <Input
              prefix={<UserOutlined style={{ color: '#bfbfbf' }} />}
              placeholder="请输入账号"
              autoComplete="username"
              autoFocus
            />
          </Form.Item>

          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password
              prefix={<LockOutlined style={{ color: '#bfbfbf' }} />}
              placeholder="请输入密码"
              autoComplete="current-password"
            />
          </Form.Item>

          <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
            <Button
              type="primary"
              htmlType="submit"
              block
              loading={submitting}
              size="large"
            >
              登录
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
