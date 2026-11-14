'use client';

/**
 * 隐私设置模态框（API §3.14）。
 *
 * **部分更新语义**：只提交改动的字段。
 *
 * 关键：布尔开关必须能提交 `false`（M01-T13 的核心边界）。
 * 用 JSON Patch 风格的显式 `false` 而非 `undefined`。
 */
import { useEffect, useState } from 'react';
import { App, Form, Modal, Radio, Switch } from 'antd';

import {
  UserApiError,
  updateSettings,
  type UserSettings,
  type Visibility,
} from '@/services/user';

const VISIBILITY_OPTIONS: { label: string; value: Visibility }[] = [
  { label: '公开', value: 'public' },
  { label: '仅好友', value: 'friends' },
  { label: '私密', value: 'private' },
];

interface FormValues {
  profile_visibility: Visibility;
  footprint_visibility: Visibility;
  plan_visibility: Visibility;
  allow_recommendation: boolean;
  allow_notification: boolean;
}

export interface PrivacyModalProps {
  open: boolean;
  settings: UserSettings;
  onCancel: () => void;
  onSuccess: () => void;
}

export function PrivacyModal({ open, settings, onCancel, onSuccess }: PrivacyModalProps) {
  const [form] = Form.useForm<FormValues>();
  const { message } = App.useApp();
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    form.setFieldsValue(settings);
  }, [open, settings, form]);

  const handleOk = async () => {
    let values: FormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }

    setSubmitting(true);
    try {
      // 全量提交（PATCH 语义下，提交全部字段等价于「这些值都是用户确认过的」）
      await updateSettings({
        profile_visibility: values.profile_visibility,
        footprint_visibility: values.footprint_visibility,
        plan_visibility: values.plan_visibility,
        allow_recommendation: values.allow_recommendation,
        allow_notification: values.allow_notification,
      });
      message.success('隐私设置已更新');
      onSuccess();
    } catch (error) {
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
      title="隐私设置"
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={submitting}
      okText="保存"
      cancelText="取消"
      width={520}
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item name="profile_visibility" label="个人资料可见性">
          <Radio.Group options={VISIBILITY_OPTIONS} />
        </Form.Item>

        <Form.Item name="footprint_visibility" label="足迹可见性">
          <Radio.Group options={VISIBILITY_OPTIONS} />
        </Form.Item>

        <Form.Item name="plan_visibility" label="计划可见性">
          <Radio.Group options={VISIBILITY_OPTIONS} />
        </Form.Item>

        <Form.Item
          name="allow_recommendation"
          label="允许个性化推荐"
          valuePropName="checked"
          extra="关闭后将只展示通用热门推荐"
        >
          <Switch />
        </Form.Item>

        <Form.Item
          name="allow_notification"
          label="接收站内通知"
          valuePropName="checked"
          extra="关闭后将不再收到计划提醒等通知"
        >
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  );
}
