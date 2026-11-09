'use client';

/**
 * 编辑旅游偏好模态框（API §3.12）。
 *
 * **整体替换语义**：保存时提交完整对象，后端会清空未传的字段。
 * 因此表单初始值必须来自当前的完整偏好，不能只传改动项。
 */
import { useEffect, useState } from 'react';
import { App, Checkbox, Form, Input, Modal, Select } from 'antd';

import {
  UserApiError,
  updateTravelProfile,
  type BudgetLevel,
  type CompanionType,
  type TravelProfile,
} from '@/services/user';

/** 可选值。与原型 `profile.html` 展示的标签一致 */
const TRAVEL_TYPE_OPTIONS = [
  '历史人文',
  '自然景色',
  '美食体验',
  '亲子游',
  '购物',
  '夜生活',
  '摄影',
  '探险',
];

const TRAVEL_STYLE_OPTIONS = ['深度游', '休闲游', '家庭出游', '穷游', '奢华游', '跟团游'];

const BUDGET_OPTIONS: { label: string; value: BudgetLevel }[] = [
  { label: '经济', value: 'economy' },
  { label: '中等', value: 'moderate' },
  { label: '舒适', value: 'comfortable' },
  { label: '豪华', value: 'luxury' },
];

const COMPANION_OPTIONS: { label: string; value: CompanionType }[] = [
  { label: '独自旅行', value: 'solo' },
  { label: '情侣出游', value: 'couple' },
  { label: '家庭出游', value: 'family' },
  { label: '朋友同行', value: 'friends' },
];

const SEASON_OPTIONS = ['春季', '夏季', '秋季', '冬季'];

interface FormValues {
  travel_types: string[];
  travel_styles: string[];
  budget_level?: BudgetLevel;
  companion_type?: CompanionType;
  preferred_seasons: string[];
  departure_city?: string;
}

export interface PreferenceModalProps {
  open: boolean;
  profile: TravelProfile;
  onCancel: () => void;
  onSuccess: () => void;
}

export function PreferenceModal({
  open,
  profile,
  onCancel,
  onSuccess,
}: PreferenceModalProps) {
  const [form] = Form.useForm<FormValues>();
  const { message } = App.useApp();
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    form.setFieldsValue({
      travel_types: profile.travel_types ?? [],
      travel_styles: profile.travel_styles ?? [],
      budget_level: profile.budget_level ?? undefined,
      companion_type: profile.companion_type ?? undefined,
      preferred_seasons: profile.preferred_seasons ?? [],
      departure_city: profile.departure_city ?? undefined,
    });
  }, [open, profile, form]);

  const handleOk = async () => {
    let values: FormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }

    setSubmitting(true);
    try {
      // **整体替换**：提交完整对象
      await updateTravelProfile({
        travel_types: values.travel_types ?? [],
        travel_styles: values.travel_styles ?? [],
        budget_level: values.budget_level ?? null,
        companion_type: values.companion_type ?? null,
        preferred_seasons: values.preferred_seasons ?? [],
        departure_city: values.departure_city?.trim() || null,
      });
      message.success('偏好已更新');
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
      title="编辑旅游偏好"
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={submitting}
      okText="保存"
      cancelText="取消"
      width={560}
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item
          name="travel_types"
          label="喜欢的类型"
          extra="最多选 10 项"
          rules={[{ type: 'array', max: 10, message: '最多选 10 项' }]}
        >
          <Checkbox.Group options={TRAVEL_TYPE_OPTIONS} />
        </Form.Item>

        <Form.Item
          name="travel_styles"
          label="旅行风格"
          extra="最多选 10 项"
          rules={[{ type: 'array', max: 10, message: '最多选 10 项' }]}
        >
          <Checkbox.Group options={TRAVEL_STYLE_OPTIONS} />
        </Form.Item>

        <Form.Item name="budget_level" label="预算偏好">
          <Select allowClear placeholder="请选择" options={BUDGET_OPTIONS} />
        </Form.Item>

        <Form.Item name="companion_type" label="同行人类型">
          <Select allowClear placeholder="请选择" options={COMPANION_OPTIONS} />
        </Form.Item>

        <Form.Item
          name="preferred_seasons"
          label="偏好季节"
          extra="最多选 4 项"
          rules={[{ type: 'array', max: 4, message: '最多选 4 项' }]}
        >
          <Checkbox.Group options={SEASON_OPTIONS} />
        </Form.Item>

        <Form.Item
          name="departure_city"
          label="默认出发城市"
          rules={[{ max: 50, message: '最多 50 字符' }]}
        >
          <Input placeholder="如：北京" maxLength={50} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
