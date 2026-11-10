'use client';

/**
 * 注册页（M01-T16，API §3.2）。
 *
 * 与登录页的区别：
 *   - 必须填密码（登录页的验证码模式会「自动注册」，无需密码）
 *   - 可选填昵称
 *   - 注册成功即登录（后端返回双 Token）
 */
import { useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Alert, App, Button, Card, Form, Input, Typography } from 'antd';
import type { InputRef } from 'antd';
import { MailOutlined, SmileOutlined } from '@ant-design/icons';

import { VerificationCodeButton } from '@/components/auth/VerificationCodeButton';
import { AuthApiError, register, sendVerificationCode } from '@/services/auth';
import { useAuthStore } from '@/stores/auth';
import {
  NICKNAME_MAX_LENGTH,
  getNicknameError,
  getTargetError,
  getVerifyCodeError,
} from '@/lib/auth/validators';

interface RegisterForm {
  target: string;
  verify_code: string;

  nickname?: string;
}

function describeError(error: AuthApiError): string {
  switch (error.code) {
    case 11003:
      return '该手机号或邮箱已被注册，请直接登录';
    case 11004:
      return '验证码错误或已过期，请重新获取';
    case 10003:
      return '操作过于频繁，请稍后再试';
    default:
      return error.message || '注册失败，请稍后重试';
  }
}

export default function RegisterPage() {
  const router = useRouter();
  const { message } = App.useApp();
  const setSession = useAuthStore((state) => state.setSession);
  const [form] = Form.useForm<RegisterForm>();
  const [loading, setLoading] = useState(false);

  //: 账号输入框引用，用于兜底读取浏览器自动填充的值
  const targetRef = useRef<InputRef>(null);

  const handleSendCode = async () => {
    let target = form.getFieldValue('target') as string | undefined;

    // **浏览器自动填充兜底**：autofill 只改 DOM 不触发 onChange，
    // antd Form 的 store 里是空的。不兜底会表现为「框里有值却提示请填写」。
    if (!target) {
      const domValue = targetRef.current?.input?.value?.trim();
      if (domValue) {
        target = domValue;
        form.setFieldValue('target', domValue);
      }
    }

    const targetError = getTargetError(target ?? '');
    if (targetError) {
      message.warning(targetError);
      throw new Error(targetError);
    }
    await sendVerificationCode({ target: target!.trim(), scene: 'register' });
    message.success('验证码已发送');
  };

  const handleSubmit = async (values: RegisterForm) => {
    setLoading(true);
    try {
      const result = await register({
        target: values.target.trim(),
        verify_code: values.verify_code,
        nickname: values.nickname?.trim() || undefined,
      });
      setSession(result.access_token, {
        user_id: result.user_id,
        nickname: values.nickname?.trim(),
        avatar_url: null,
      });
      message.success('注册成功');
      router.replace('/');
    } catch (error) {
      message.error(error instanceof AuthApiError ? describeError(error) : '注册失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="page-container"
      style={{ display: 'flex', justifyContent: 'center', paddingTop: 48 }}
    >
      <Card style={{ width: 440 }}>
        <Typography.Title level={3} style={{ textAlign: 'center', marginBottom: 24 }}>
          注册云游坊
        </Typography.Title>

        <Form form={form} layout="vertical" requiredMark={false} onFinish={handleSubmit}>
          <Form.Item
            name="target"
            label="手机号 / 邮箱"
            rules={[
              {
                validator: (_, value: string) => {
                  const error = getTargetError(value ?? '');
                  return error ? Promise.reject(new Error(error)) : Promise.resolve();
                },
              },
            ]}
          >
            <Input
              ref={targetRef}
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

          {/* 注册不设密码（需求 2.1.1）：账号创建后可用验证码登录，
              需要密码时可在「个人中心 → 修改密码」中设置。 */}
          <Alert
            type="info"
            showIcon
            message="注册后可用验证码登录"
            description="如需密码登录，可在注册完成后到「个人中心 → 修改密码」设置。"
            style={{ marginBottom: 24 }}
          />

          <Form.Item
            name="nickname"
            label="昵称（可选）"
            rules={[
              {
                validator: (_, value: string | undefined) => {
                  const error = getNicknameError(value);
                  return error ? Promise.reject(new Error(error)) : Promise.resolve();
                },
              },
            ]}
          >
            <Input
              prefix={<SmileOutlined />}
              placeholder="不填将自动生成"
              size="large"
              maxLength={NICKNAME_MAX_LENGTH}
            />
          </Form.Item>

          <Button type="primary" htmlType="submit" block size="large" loading={loading}>
            注册
          </Button>
        </Form>

        <div style={{ marginTop: 16, textAlign: 'center' }}>
          <Link href="/login" style={{ color: '#1677ff' }}>
            已有账号？立即登录
          </Link>
        </div>
      </Card>
    </div>
  );
}
