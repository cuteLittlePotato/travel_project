/**
 * 餐厅编辑模态框（M11-T12）。
 *
 * 字段按原型 `restaurants.html`：名称 / 类型 / 城市 / 人均消费 / 营业时间 / 特色菜 / 图片 / 状态。
 */
import { useEffect, useState } from 'react';
import { App, Col, Form, Input, InputNumber, Modal, Row, Select, Switch } from 'antd';

import { OpeningHoursField } from '@/components/form/OpeningHoursField';
import { getRestaurant } from '@/services/catalog';
import {
  createRestaurant,
  listCities,
  updateRestaurant,
  type RestaurantPayload,
} from '@/services/catalog';

interface FormValues {
  name: string;
  city_id: string;
  cuisine_type?: string;
  summary?: string;
  avg_cost?: number;
  business_hours?: Record<string, string> | null;
  signature_dishes?: string[];
  image_urls?: string;
  address?: string;
  phone?: string;
  need_reservation?: boolean;
  is_published?: boolean;
}

export interface RestaurantModalProps {
  open: boolean;
  /** 编辑时传记录 ID；新建时不传 */
  restaurantId?: string;
  onCancel: () => void;
  onSuccess: () => void;
}

export function RestaurantModal({
  open,
  restaurantId,
  onCancel,
  onSuccess,
}: RestaurantModalProps) {
  const [form] = Form.useForm<FormValues>();
  const { message } = App.useApp();
  const [submitting, setSubmitting] = useState(false);
  const [cities, setCities] = useState<{ label: string; value: string }[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);

  const isEdit = Boolean(restaurantId);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;

    async function load() {
      try {
        const cityRes = await listCities({ page: 1, page_size: 100 });
        if (cancelled) return;
        setCities(cityRes.items.map((c) => ({ label: c.name, value: c.id })));

        if (isEdit && restaurantId) {
          // 详情接口返回全部可编辑字段——列表只含展示字段，不足以回填
          setDetailLoading(true);
          try {
            const detail = await getRestaurant(restaurantId);
            if (cancelled) return;
            form.setFieldsValue({
              name: detail.name,
              city_id: detail.city_id,
              cuisine_type: detail.cuisine_type ?? undefined,
              address: detail.address ?? undefined,
              summary: detail.summary ?? undefined,
              avg_cost: detail.avg_cost ? Number(detail.avg_cost) : undefined,
              business_hours: detail.business_hours,
              signature_dishes: detail.signature_dishes ?? undefined,
              need_reservation: detail.need_reservation,
              phone: detail.phone ?? undefined,
              is_published: detail.is_published,
            });
          } catch {
            if (!cancelled) message.error('加载餐厅详情失败');
          } finally {
            if (!cancelled) setDetailLoading(false);
          }
        } else {
          form.resetFields();
          form.setFieldsValue({ is_published: true, need_reservation: false });
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
  }, [open, restaurantId, isEdit]);

  const handleOk = async () => {
    let values: FormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }

    setSubmitting(true);
    try {
      const payload: RestaurantPayload = {
        name: values.name.trim(),
        city_id: values.city_id,
        cuisine_type: values.cuisine_type?.trim() || null,
        avg_cost: values.avg_cost != null ? String(values.avg_cost) : null,
        business_hours: values.business_hours ?? null,
        signature_dishes: values.signature_dishes?.length ? values.signature_dishes : null,
        image_urls: values.image_urls?.trim() ? [values.image_urls.trim()] : null,
        address: values.address?.trim() || null,
        phone: values.phone?.trim() || null,
        need_reservation: values.need_reservation ?? false,
        is_published: values.is_published ?? true,
      };

      if (isEdit && restaurantId) {
        await updateRestaurant(restaurantId, payload);
        message.success('餐厅已更新');
      } else {
        await createRestaurant(payload);
        message.success('餐厅已创建');
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
      loading={detailLoading}
      title={isEdit ? '编辑餐厅' : '新增餐厅'}
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
          label="餐厅名称"
          rules={[
            { required: true, message: '请输入餐厅名称' },
            { max: 100, message: '最多 100 字符' },
          ]}
        >
          <Input placeholder="如：全聚德烤鸭店" maxLength={100} />
        </Form.Item>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="cuisine_type" label="菜系类型">
              <Input placeholder="如：川菜、粤菜" maxLength={50} />
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

        <Form.Item name="avg_cost" label="人均消费（元）">
          <InputNumber min={0} precision={2} style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item name="business_hours" label="营业时间">
          <OpeningHoursField />
        </Form.Item>

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
            <Form.Item name="image_urls" label="封面图 URL">
              <Input placeholder="https://..." maxLength={500} />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item name="signature_dishes" label="特色菜">
          <Select mode="tags" placeholder="输入后回车添加" tokenSeparators={[',', '，']} />
        </Form.Item>

        <Form.Item name="need_reservation" label="需提前预约" valuePropName="checked">
          <Switch />
        </Form.Item>

        <Form.Item name="is_published" label="营业状态" valuePropName="checked">
          <Switch checkedChildren="营业中" unCheckedChildren="已下架" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
