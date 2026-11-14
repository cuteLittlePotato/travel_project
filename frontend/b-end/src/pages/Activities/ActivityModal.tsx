/**
 * 活动编辑模态框（M11-T13，API §12.32 / §12.33）。
 *
 * **无价格字段**（评审 §Q3）：活动定价模式差异大，通过 `detail_url` 外链到
 * 详情页展示。表单只收集基本信息与时间、适用范围。
 *
 * **无状态字段**：状态由 `start_date` / `end_date` 实时计算，表单不提供。
 */
import { useEffect, useState } from 'react';
import {
  App,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Switch,
} from 'antd';
import dayjs, { type Dayjs } from 'dayjs';

import {
  createActivity,
  updateActivity,
  type ActivityPayload,
  type ActivityType,
} from '@/services/catalog';

const TYPE_OPTIONS: { label: string; value: ActivityType }[] = [
  { label: '特惠', value: 'discount' },
  { label: '节庆', value: 'festival' },
  { label: '展览', value: 'exhibition' },
  { label: '其他', value: 'other' },
];

export interface ActivityFormValues {
  title: string;
  activity_type?: ActivityType;
  date_range: [Dayjs, Dayjs];
  description?: string;
  cover_image_url?: string;
  detail_url?: string;
  sort_weight?: number;
  is_published?: boolean;
}

export interface ActivityModalProps {
  open: boolean;
  /** 编辑时传入的初始值（活动列表项） */
  initial?: {
    id: string;
    title: string;
    activity_type: ActivityType | null;
    start_date: string;
    end_date: string;
    description: string | null;
    cover_image_url: string | null;
    detail_url: string | null;
    sort_weight: number;
    is_published: boolean;
  };
  onCancel: () => void;
  onSuccess: () => void;
}

export function ActivityModal({ open, initial, onCancel, onSuccess }: ActivityModalProps) {
  const [form] = Form.useForm<ActivityFormValues>();
  const { message } = App.useApp();
  const [submitting, setSubmitting] = useState(false);

  const isEdit = Boolean(initial);

  useEffect(() => {
    if (!open) return;

    if (initial) {
      form.setFieldsValue({
        title: initial.title,
        activity_type: initial.activity_type ?? undefined,
        date_range: [dayjs(initial.start_date), dayjs(initial.end_date)],
        description: initial.description ?? undefined,
        cover_image_url: initial.cover_image_url ?? undefined,
        detail_url: initial.detail_url ?? undefined,
        sort_weight: initial.sort_weight,
        is_published: initial.is_published,
      });
    } else {
      form.resetFields();
      form.setFieldsValue({ is_published: true, sort_weight: 0 });
    }
  }, [open, initial, form]);

  const handleOk = async () => {
    let values: ActivityFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }

    const [start, end] = values.date_range;

    setSubmitting(true);
    try {
      const payload: ActivityPayload = {
        title: values.title.trim(),
        activity_type: values.activity_type ?? null,
        start_date: start.format('YYYY-MM-DD'),
        end_date: end.format('YYYY-MM-DD'),
        description: values.description?.trim() || null,
        cover_image_url: values.cover_image_url?.trim() || null,
        detail_url: values.detail_url?.trim() || null,
        sort_weight: values.sort_weight ?? 0,
        is_published: values.is_published ?? true,
      };

      if (isEdit && initial) {
        await updateActivity(initial.id, payload);
        message.success('活动已更新');
      } else {
        await createActivity(payload);
        message.success('活动已创建');
      }
      onSuccess();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title={isEdit ? '编辑活动' : '新增活动'}
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={submitting}
      okText="保存"
      cancelText="取消"
      width={640}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item
          name="title"
          label="活动标题"
          rules={[
            { required: true, message: '请输入活动标题' },
            { max: 200, message: '最多 200 字符' },
          ]}
        >
          <Input placeholder="如：故宫春季特展" maxLength={200} />
        </Form.Item>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="activity_type" label="活动类型">
              <Select allowClear placeholder="选择类型" options={TYPE_OPTIONS} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="sort_weight" label="排序权重">
              <InputNumber
                min={0}
                style={{ width: '100%' }}
                placeholder="数值越大越靠前"
              />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item
          name="date_range"
          label="活动时间"
          rules={[
            { required: true, message: '请选择活动时间' },
            {
              validator: (_, value?: [Dayjs, Dayjs]) => {
                if (!value || value.length !== 2) return Promise.resolve();
                const [start, end] = value;
                if (end.isBefore(start, 'day')) {
                  return Promise.reject(new Error('结束日期不能早于开始日期'));
                }
                return Promise.resolve();
              },
            },
          ]}
        >
          <DatePicker.RangePicker style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item name="description" label="活动描述">
          <Input.TextArea rows={3} placeholder="活动详情描述" maxLength={1000} showCount />
        </Form.Item>

        <Form.Item
          name="cover_image_url"
          label="封面图 URL"
          rules={[
            {
              validator: (_, value?: string) => {
                if (!value) return Promise.resolve();
                if (!/^https?:\/\//.test(value)) {
                  return Promise.reject(new Error('请输入以 http(s):// 开头的地址'));
                }
                return Promise.resolve();
              },
            },
          ]}
        >
          <Input placeholder="https://..." maxLength={500} />
        </Form.Item>

        <Form.Item
          name="detail_url"
          label="详情页链接"
          extra="活动的价格、优惠等信息在此页面展示"
          rules={[
            {
              validator: (_, value?: string) => {
                if (!value) return Promise.resolve();
                if (!/^https?:\/\//.test(value)) {
                  return Promise.reject(new Error('请输入以 http(s):// 开头的地址'));
                }
                return Promise.resolve();
              },
            },
          ]}
        >
          <Input placeholder="https://..." maxLength={500} />
        </Form.Item>

        <Form.Item name="is_published" label="上架状态" valuePropName="checked">
          <Switch checkedChildren="已上架" unCheckedChildren="已下架" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
