'use client';

/**
 * 登录页（M01-T16）。
 *
 * 三种登录方式切换：
 *   - 密码登录（API §3.3）
 *   - 验证码登录，未注册自动注册（API §3.4）
 *   - 第三方登录（API §3.5，当前未开放）
 *
 * Token 策略（评审 §Q1）：Access Token 存内存（Zustand），
 * Refresh Token 由后端写入 httpOnly Cookie。**不碰 localStorage**。
 */
import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { App, Button, Card, Divider, Form, Input, Segmented, Typography } from 'antd';
import { LockOutlined, MailOutlined } from '@ant-design/icons';

import { OAuthButtons } from '@/components/auth/OAuthButtons';
import { describeError } from './describe-error';
import { VerificationCodeButton } from '@/components/auth/VerificationCodeButton';
import {
  AuthApiError,
  login,
  loginByCode,
  sendVerificationCode,
  type LoginResult,
} from '@/services/auth';
import { useAuthStore } from '@/stores/auth';
import {
  getPasswordError,
  getTargetError,
  getVerifyCodeError,
} from '@/lib/auth/validators';
import type { AuthUser } from '@/stores/auth';

type LoginMode = '密码登录' | '验证码登录';

interface PasswordForm {
  target: string;
  password: string;
}

interface CodeForm {
  target: string;
  verify_code: string;
}

/** 登录成功后写入内存并跳转 */
function persistSession(
  result: LoginResult,
  setSession: (token: string, user: AuthUser) => void,
) {
  setSession(result.access_token, {
    user_id: result.user_id,
    nickname: undefined,
    avatar_url: null,
  });
}

function LoginPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { message } = App.useApp();
  const setSession = useAuthStore((state) => state.setSession);

  const [mode, setMode] = useState<LoginMode>('密码登录');
  const [loading, setLoading] = useState(false);
  const [passwordForm] = Form.useForm<PasswordForm>();
  const [codeForm] = Form.useForm<CodeForm>();

  const redirectTo = searchParams.get('redirect') ?? '/';

  const handlePasswordLogin = async (values: PasswordForm) => {
    setLoading(true);
    try {
      const result = await login(values);
      persistSession(result, setSession);
      message.success('登录成功');
      router.replace(redirectTo);
    } catch (error) {
      message.error(error instanceof AuthApiError ? describeError(error) : '登录失败');
    } finally {
      setLoading(false);
    }
  };

  const handleCodeLogin = async (values: CodeForm) => {
    setLoading(true);
    try {
      const result = await loginByCode(values);
      persistSession(result, setSession);
      message.success(result.is_new_user ? '注册成功，欢迎加入' : '登录成功');
      router.replace(redirectTo);
    } catch (error) {
      message.error(error instanceof AuthApiError ? describeError(error) : '登录失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSendCode = async () => {
    const target = codeForm.getFieldValue('target') as string | undefined;
    const targetError = getTargetError(target ?? '');
    if (targetError) {
      message.warning(targetError);
      throw new Error(targetError);
    }
    await sendVerificationCode({ target: target!.trim(), scene: 'login' });
    message.success('验证码已发送');
  };



  return (
    <div
      className="page-container"
      style={{ display: 'flex', justifyContent: 'center', paddingTop: 64 }}
    >
      <Card style={{ width: 420 }}>
        <Typography.Title level={3} style={{ textAlign: 'center', marginBottom: 24 }}>
          登录云游坊
        </Typography.Title>

        <Segmented
          block
          options={['密码登录', '验证码登录']}
          value={mode}
          onChange={(value) => setMode(value as LoginMode)}
          style={{ marginBottom: 24 }}
        />

        {mode === '密码登录' ? (
          <Form<PasswordForm>
            form={passwordForm}
            layout="vertical"
            requiredMark={false}
            onFinish={handlePasswordLogin}
          >
            <Form.Item
              name="target"
              label="手机号 / 邮箱 / 用户名"
              rules={[{ required: true, message: '请输入账号' }]}
            >
              <Input
                prefix={<MailOutlined />}
                placeholder="请输入账号"
                size="large"
                autoComplete="username"
              />
            </Form.Item>

            <Form.Item
              name="password"
              label="密码"
              rules={[
                { required: true, message: '请输入密码' },
                {
                  validator: (_, value: string) => {
                    const error = getPasswordError(value ?? '');
                    return error ? Promise.reject(new Error(error)) : Promise.resolve();
                  },
                },
              ]}
            >
              <Input.Password
                prefix={<LockOutlined />}
                placeholder="请输入密码"
                size="large"
                autoComplete="current-password"
              />
            </Form.Item>

            <Button type="primary" htmlType="submit" block size="large" loading={loading}>
              登录
            </Button>
          </Form>
        ) : (
          <Form<CodeForm>
            form={codeForm}
            layout="vertical"
            requiredMark={false}
            onFinish={handleCodeLogin}
          >
            <Form.Item
              name="target"
              label="手机号 / 邮箱"
              rules={[
                { required: true, message: '请输入账号' },
                {
                  validator: (_, value: string) => {
                    const error = getTargetError(value ?? '');
                    return error ? Promise.reject(new Error(error)) : Promise.resolve();
                  },
                },
              ]}
            >
              <Input
                prefix={<MailOutlined />}
                placeholder="请输入手机号或邮箱"
                size="large"
                autoComplete="username"
              />
            </Form.Item>

            <Form.Item label="验证码" required>
              <div style={{ display: 'flex', gap: 8 }}>
                <Form.Item
                  name="verify_code"
                  noStyle
                  rules={[
                    {
                      validator: (_, value: string) => {
                        const error = getVerifyCodeError(value ?? '');
                        return error ? Promise.reject(new Error(error)) : Promise.resolve();
                      },
                    },
                  ]}
                >
                  <Input placeholder="6 位验证码" size="large" maxLength={6} />
                </Form.Item>
                <VerificationCodeButton size="large" onSend={handleSendCode} />
              </div>
            </Form.Item>

            <Button type="primary" htmlType="submit" block size="large" loading={loading}>
              登录 / 注册
            </Button>
          </Form>
        )}

        <Divider plain style={{ color: '#8c8c8c', fontSize: 12 }}>
          第三方登录
        </Divider>
        <OAuthButtons enabled={false} />

        <div style={{ marginTop: 24, textAlign: 'center' }}>
          <Link href="/register" style={{ color: '#1677ff' }}>
            还没有账号？使用邮箱注册
          </Link>
        </div>
      </Card>
    </div>
  );
}

/**
 * Next.js 14 要求使用 useSearchParams 的组件被 Suspense 包裹，
 * 否则构建期预渲染会报 "missing-suspense-with-csr-bailout"。
 */
export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginPageContent />
    </Suspense>
  );
}
