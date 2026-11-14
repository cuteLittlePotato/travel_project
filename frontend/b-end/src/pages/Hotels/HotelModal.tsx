/**
 * 酒店编辑模态框（M11-T12）。
 *
 * 字段按原型 `hotels.html`：名称 / 星级 / 城市 / 价格区间 / 房型 / 设施 / 状态。
 * 价格区间校验 min <= max（前后端都校验，前端更早拦截）。
 */
import { useEffect, useState } from 'react';
import { App, Col, Form, Input, InputNumber, Modal, Row, Select, Switch } from 'antd';

import {
  createHotel,
  listCities,
  updateHotel,
  type HotelPayload,
} from '@/services/catalog';

const STAR_OPTIONS = [
  { label: '五星级', value: 'five' },
  { label: '四星级', value: 'four' },
  { label: '三星级', value: 'three' },
  { label: '二星级', value: 'two' },
  { label: '一星级', value: 'one' },
  { label: '精品酒店', value: 'boutique' },
];

const FACILITY_OPTIONS = [
  '免费WiFi', '停车场', '健身房', '游泳池', '餐厅',
  '接机服务', '行李寄存', '24小时前台', '洗衣服务',
];

interface FormValues {
  name: string;
  city_id: string;
  star_level?: string;
  min_price?: number;
  max_price?: number;
  address?: string;
  phone?: string;
  booking_url?: string;
  room_types?: string[];
  facilities?: string[];
  is_published?: boolean;
}

export interface HotelModalProps {
  open: boolean;
  hotelId?: string;
  onCancel: () => void;
  onSuccess: () => void;
}

export function HotelModal({ open, hotelId, onCancel, onSuccess }: HotelModalProps) {
  const [form] = Form.useForm<FormValues>();
  const { message } = App.useApp();
  const [submitting, setSubmitting] = useState(false);
  const [cities, setCities] = useState<{ label: string; value: string }[]>([]);

  const isEdit = Boolean(hotelId);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;

    async function load() {
      try {
        const cityRes = await listCities({ page: 1, page_size: 100 });
        if (cancelled) return;
        setCities(cityRes.items.map((c) => ({ label: c.name, value: c.id })));

        if (!isEdit) {
          form.resetFields();
          form.setFieldsValue({ is_published: true });
        }
      } catch {
        if (!cancelled) message.error('加载城市列表失败');
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, hotelId, isEdit]);

  const handleOk = async () => {
    let values: FormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }

    setSubmitting(true);
    try {
      const payload: HotelPayload = {
        name: values.name.trim(),
        city_id: values.city_id,
        star_level: values.star_level ?? null,
        min_price: values.min_price != null ? String(values.min_price) : null,
        max_price: values.max_price != null ? String(values.max_price) : null,
        address: values.address?.trim() || null,
        phone: values.phone?.trim() || null,
        booking_url: values.booking_url?.trim() || null,
        // 房型在后端是 [{name, price}] 结构，这里简化为按名称建条目
        room_types: values.room_types?.length
          ? values.room_types.map((name) => ({ name }))
          : null,
        facilities: values.facilities?.length ? values.facilities : null,
        is_published: values.is_published ?? true,
      };

      if (isEdit && hotelId) {
        await updateHotel(hotelId, payload);
        message.success('酒店已更新');
      } else {
        await createHotel(payload);
        message.success('酒店已创建');
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
      title={isEdit ? '编辑酒店' : '新增酒店'}
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
          name="name"
          label="酒店名称"
          rules={[
            { required: true, message: '请输入酒店名称' },
            { max: 100, message: '最多 100 字符' },
          ]}
        >
          <Input placeholder="如：北京王府井希尔顿酒店" maxLength={100} />
        </Form.Item>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="star_level" label="星级">
              <Select allowClear placeholder="选择星级" options={STAR_OPTIONS} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="city_id"
              label="城市"
              rules={[{ required: true, message: '请选择城市' }]}
            >
              <Select showSearch placeholder="选择城市" options={cities} optionFilterProp="label" />
            </Form.Item>
          </Col>
        </Row>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="min_price" label="最低价（元）">
              <InputNumber min={0} precision={2} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="max_price"
              label="最高价（元）"
              dependencies={['min_price']}
              rules={[
                ({ getFieldValue }) => ({
                  validator: (_, value?: number) => {
                    const min = getFieldValue('min_price') as number | undefined;
                    if (value != null && min != null && value < min) {
                      return Promise.reject(new Error('最高价不能低于最低价'));
                    }
                    return Promise.resolve();
                  },
                }),
              ]}
            >
              <InputNumber min={0} precision={2} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item name="address" label="地址">
          <Input placeholder="详细地址" maxLength={255} />
        </Form.Item>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="phone" label="联系电话">
              <Input placeholder="选填" maxLength={50} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="booking_url" label="预订链接">
              <Input placeholder="https://..." maxLength={500} />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item name="room_types" label="房型">
          <Select mode="tags" placeholder="输入后回车添加，如：标准双人间" tokenSeparators={[',', '，']} />
        </Form.Item>

        <Form.Item name="facilities" label="设施">
          <Select
            mode="multiple"
            placeholder="选择设施"
            options={FACILITY_OPTIONS.map((f) => ({ label: f, value: f }))}
          />
        </Form.Item>

        <Form.Item name="is_published" label="上架状态" valuePropName="checked">
          <Switch checkedChildren="已上架" unCheckedChildren="已下架" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
