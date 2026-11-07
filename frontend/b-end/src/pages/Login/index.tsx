/**
 * B 端登录页。
 *
 * 后端接口（API §14.14）在 M15 任务中实现，当前只完成表单与交互骨架，
 * 提交时给出明确的未接线提示，避免静默失败。
 */
import { useState } from 'react';
import { Button, Card, Form, Input, Typography, App } from 'antd';
import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

import { request } from '@/services/http';
import { useAdminAuthStore, type AdminUser } from '@/stores/auth';

interface LoginForm {
  username: string;
  password: string;
}

interface LoginResult {
  access_token: string;
  admin: AdminUser;
}

export function LoginPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const { message } = App.useApp();
  const setSession = useAdminAuthStore((state) => state.setSession);

  const handleSubmit = async (values: LoginForm) => {
    setLoading(true);
    try {
      const result = await request<LoginResult>({
        url: '/auth/login',
        method: 'POST',
        data: values,
      });
      setSession(result.access_token, result.admin);
      navigate('/dashboard', { replace: true });
    } catch (error) {
      message.error(error instanceof Error ? error.message : '登录失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f5f7fa',
      }}
    >
      <Card style={{ width: 380 }}>
        <Typography.Title level={3} style={{ textAlign: 'center' }}>
          云游坊运营后台
        </Typography.Title>
        <Form<LoginForm> layout="vertical" onFinish={handleSubmit} requiredMark={false}>
          <Form.Item
            name="username"
            label="账号"
            rules={[{ required: true, message: '请输入账号' }]}
          >
            <Input prefix={<UserOutlined />} placeholder="请输入账号" autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="请输入密码"
              autoComplete="current-password"
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" block loading={loading}>
              登录
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
