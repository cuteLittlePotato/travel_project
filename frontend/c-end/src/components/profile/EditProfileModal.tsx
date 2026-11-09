'use client';

/**
 * 编辑资料模态框（API §3.9）。
 *
 * 只编辑四个字段：昵称、头像、性别、常驻地区。
 * 用户名（`username`）不可修改——它是内部标识，与登录绑定。
 *
 * 边界（DoD）：保存失败时**保留表单状态不清空**，用户可直接重试。
 */
import { useEffect, useState } from 'react';
import { App, Form, Input, Modal, Radio } from 'antd';

import { RegionCascader } from '@/components/common/RegionCascader';
import {
  UserApiError,
  updateProfile,
  type Gender,
  type UserProfile,
} from '@/services/user';

interface FormValues {
  nickname: string;
  avatar_url?: string;
  gender?: Gender;
  region_code?: string;
}

export interface EditProfileModalProps {
  open: boolean;
  profile: UserProfile;
  onCancel: () => void;
  onSuccess: () => void;
}

export function EditProfileModal({
  open,
  profile,
  onCancel,
  onSuccess,
}: EditProfileModalProps) {
  const [form] = Form.useForm<FormValues>();
  const { message } = App.useApp();
  const [submitting, setSubmitting] = useState(false);

  // 每次打开时用当前资料回填，避免上次的编辑残留
  useEffect(() => {
    if (!open) return;
    form.setFieldsValue({
      nickname: profile.nickname,
      avatar_url: profile.avatar_url ?? undefined,
      gender: profile.gender ?? undefined,
      region_code: profile.region_code ?? undefined,
    });
  }, [open, profile, form]);

  const handleOk = async () => {
    let values: FormValues;
    try {
      values = await form.validateFields();
    } catch {
      return; // 校验失败不提交
    }

    setSubmitting(true);
    try {
      await updateProfile({
        nickname: values.nickname.trim(),
        avatar_url: values.avatar_url?.trim() || null,
        gender: values.gender ?? null,
        region_code: values.region_code || null,
      });
      message.success('资料已更新');
      onSuccess();
    } catch (error) {
      // **不关闭模态框、不清空表单**——用户可修正后重试
      // 不能只判断 instanceof：UserApiError 的 message 可能是空串
      // （后端 204 却走了错误分支时），那样会弹出「只有红叉没有文字」的空提示
      const detail =
        error instanceof UserApiError ? error.message?.trim() : '';
      message.error(detail || '保存失败，请重试');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title="编辑资料"
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={submitting}
      okText="保存"
      cancelText="取消"
      destroyOnClose={false}
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item
          name="nickname"
          label="昵称"
          rules={[
            { required: true, message: '请输入昵称' },
            { max: 50, message: '昵称最多 50 字符' },
            { whitespace: true, message: '昵称不能为空白' },
          ]}
        >
          <Input placeholder="请输入昵称" maxLength={50} />
        </Form.Item>

        <Form.Item
          name="avatar_url"
          label="头像地址"
          rules={[
            {
              validator: (_, value?: string) => {
                if (!value) return Promise.resolve();
                if (!/^https?:\/\//.test(value)) {
                  return Promise.reject(new Error('请输入以 http(s):// 开头的地址'));
                }
                if (value.length > 500) {
                  return Promise.reject(new Error('地址不能超过 500 字符'));
                }
                return Promise.resolve();
              },
            },
          ]}
        >
          <Input placeholder="https://example.com/avatar.jpg" maxLength={500} />
        </Form.Item>

        <Form.Item name="gender" label="性别">
          <Radio.Group>
            <Radio value="male">男</Radio>
            <Radio value="female">女</Radio>
            <Radio value="secret">保密</Radio>
          </Radio.Group>
        </Form.Item>

        <Form.Item name="region_code" label="常驻地区" extra="用于推荐附近的城市">
          <RegionCascader />
        </Form.Item>
      </Form>
    </Modal>
  );
}
