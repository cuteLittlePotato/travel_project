'use client';

/**
 * 账号注销弹窗（API §3.19）。
 *
 * **不可逆操作**，因此设了两道门槛：
 *   1. 输入密码验证身份——Access Token 可能被盗用，不能只凭它注销
 *   2. 手动输入「注销」二字——防止误点
 *
 * 后端也校验这两项，前端拦截只是减少误操作，不是安全边界。
 */
import { useEffect, useState } from 'react';
import { Alert, App, Form, Input, Modal, Typography } from 'antd';

import { UserApiError, deactivateAccount } from '@/services/user';

interface FormValues {
  password: string;
  confirmation: string;
}

export interface DeactivateAccountModalProps {
  open: boolean;
  onCancel: () => void;
  /** 注销成功回调（通常是清本地状态并跳登录页） */
  onSuccess: () => void;
}

export function DeactivateAccountModal({
  open,
  onCancel,
  onSuccess,
}: DeactivateAccountModalProps) {
  const [form] = Form.useForm<FormValues>();
  const { message } = App.useApp();
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) form.resetFields();
  }, [open, form]);

  const handleOk = async () => {
    let values: FormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }

    setSubmitting(true);
    try {
      await deactivateAccount({
        password: values.password,
        confirmation: values.confirmation,
      });
      message.success('账号已注销');
      onSuccess();
    } catch (error) {
      const detail = error instanceof UserApiError ? error.message?.trim() : '';
      message.error(detail || '注销失败，请重试');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title="注销账号"
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={submitting}
      okText="确认注销"
      cancelText="取消"
      okButtonProps={{ danger: true }}
      width={480}
      destroyOnHidden
    >
      <Alert
        type="error"
        showIcon
        message="此操作不可恢复"
        description={
          <div style={{ fontSize: 13 }}>
            注销后：
            <ul style={{ margin: '6px 0', paddingLeft: 18 }}>
              <li>所有设备立即退出登录</li>
              <li>对话记录、长期记忆、额度记录被清除</li>
              <li>足迹保留但作者显示为「已注销用户」</li>
              <li>同一账号无法再次登录</li>
            </ul>
          </div>
        }
        style={{ marginBottom: 16 }}
      />

      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item
          name="password"
          label="当前密码"
          extra="用于确认是本人操作"
          rules={[{ required: true, message: '请输入密码' }]}
        >
          <Input.Password
            placeholder="请输入当前密码"
            autoComplete="current-password"
          />
        </Form.Item>

        <Form.Item
          name="confirmation"
          label={
            <span>
              请输入 <Typography.Text code>注销</Typography.Text> 以确认
            </span>
          }
          rules={[
            { required: true, message: '请输入「注销」' },
            {
              validator: (_, value?: string) => {
                if (!value || value.trim() === '') return Promise.resolve();
                if (value.trim() !== '注销') {
                  return Promise.reject(new Error('请准确输入「注销」两个字'));
                }
                return Promise.resolve();
              },
            },
          ]}
        >
          <Input placeholder="注销" maxLength={10} autoComplete="off" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
