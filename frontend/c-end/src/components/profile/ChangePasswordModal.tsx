'use client';

/**
 * 修改密码模态框（API §3.10）。
 *
 * **无密码账号的特殊处理**（2026-11-08 确认）：
 * 自动注册/第三方登录的账号首次设置密码时，`old_password` 可为空。
 * 这里不主动检测账号是否有密码（需额外接口），
 * 而是让后端判断——若账号已有密码但未传旧密码，后端返回 11006，前端提示。
 */
import { useState } from 'react';
import { App, Form, Input, Modal } from 'antd';

import { UserApiError, changePassword } from '@/services/user';
import {
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  getPasswordError,
} from '@/lib/auth/validators';

interface FormValues {
  old_password?: string;
  new_password: string;
  confirm_password: string;
}

export interface ChangePasswordModalProps {
  open: boolean;
  onCancel: () => void;
  onSuccess: () => void;
}

export function ChangePasswordModal({
  open,
  onCancel,
  onSuccess,
}: ChangePasswordModalProps) {
  const [form] = Form.useForm<FormValues>();
  const { message } = App.useApp();
  const [submitting, setSubmitting] = useState(false);

  const handleOk = async () => {
    let values: FormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }

    setSubmitting(true);
    try {
      await changePassword({
        old_password: values.old_password?.trim() || undefined,
        new_password: values.new_password,
      });
      onSuccess();
    } catch (error) {
      if (error instanceof UserApiError) {
        if (error.code === 11006) {
          message.error('原密码错误，或该账号尚未设置密码（可留空原密码）');
        } else if (error.code === 11011) {
          message.error('新密码不能与原密码相同');
        } else {
          message.error(error.message);
        }
      } else {
        message.error('修改失败，请重试');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title="修改密码"
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={submitting}
      okText="确认修改"
      cancelText="取消"
      okButtonProps={{ danger: true }}
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item
          name="old_password"
          label="原密码"
          extra="若账号尚未设置密码（如通过验证码或第三方登录注册），可留空"
        >
          <Input.Password placeholder="请输入原密码" autoComplete="current-password" />
        </Form.Item>

        <Form.Item
          name="new_password"
          label="新密码"
          extra={`${PASSWORD_MIN_LENGTH}-${PASSWORD_MAX_LENGTH} 位，需同时包含字母与数字`}
          rules={[
            {
              validator: (_, value: string) => {
                const error = getPasswordError(value ?? '');
                return error ? Promise.reject(new Error(error)) : Promise.resolve();
              },
            },
          ]}
        >
          <Input.Password placeholder="请输入新密码" autoComplete="new-password" />
        </Form.Item>

        <Form.Item
          name="confirm_password"
          label="确认新密码"
          dependencies={['new_password']}
          rules={[
            { required: true, message: '请再次输入新密码' },
            ({ getFieldValue }) => ({
              validator: (_, value: string) => {
                if (value && value !== getFieldValue('new_password')) {
                  return Promise.reject(new Error('两次输入的密码不一致'));
                }
                return Promise.resolve();
              },
            }),
          ]}
        >
          <Input.Password placeholder="请再次输入新密码" autoComplete="new-password" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
