/**
 * 景点编辑模态框（M11-T11）。
 *
 * 字段对齐原型 `attractions.html` 的 11 个表单项：
 * 名称 / 省份 / 城市 / 分类 / 简介 / 票价 / 热度 / 开放时间 / 游玩时长 / 最佳季节。
 *
 * 省份-城市级联：选省后过滤出该省城市，改省时清空已选城市。
 */
import { useEffect, useMemo, useState } from 'react';

import { ImageUrlsField } from './ImageUrlsField';
import { OpeningHoursField } from '@/components/form/OpeningHoursField';
import { App, Col, Form, Input, InputNumber, Modal, Row, Select, Switch } from 'antd';

import {
  createAttraction,
  getAttraction,
  listCategories,
  listCities,
  listProvinces,
  updateAttraction,
  type Attraction,
  type AttractionPayload,
  type Category,
  type CityListItem,
  type ProvinceListItem,
} from '@/services/catalog';

interface FormValues {
  name: string;
  province_id?: string;
  city_id: string;
  category_ids: string[];
  summary?: string;
  image_urls?: string[] | null;
  ticket_price?: number;
  base_popularity?: number;
  opening_hours?: Record<string, string> | null;
  visit_duration_minutes?: number;
  best_seasons?: string[];
  is_published?: boolean;
}

const SEASON_OPTIONS = ['春季', '夏季', '秋季', '冬季'];

export interface AttractionModalProps {
  open: boolean;
  /** 传 id 表示编辑，不传表示新建 */
  attractionId?: string;
  onCancel: () => void;
  onSuccess: () => void;
}

export function AttractionModal({
  open,
  attractionId,
  onCancel,
  onSuccess,
}: AttractionModalProps) {
  const [form] = Form.useForm<FormValues>();
  const { message } = App.useApp();
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(false);

  const [provinces, setProvinces] = useState<ProvinceListItem[]>([]);
  const [cities, setCities] = useState<CityListItem[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);

  const isEdit = Boolean(attractionId);

  // 省份切换时过滤城市（级联）
  const provinceId = Form.useWatch('province_id', form);
  const cityOptions = useMemo(() => {
    const filtered = provinceId
      ? cities.filter((c) => c.parent_id === provinceId)
      : cities;
    return filtered.map((c) => ({ label: c.name, value: c.id }));
  }, [cities, provinceId]);

  // 打开时加载选项；编辑模式拉取详情
  useEffect(() => {
    if (!open) return;

    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const [provinceRes, categoryRes] = await Promise.all([
          listProvinces(),
          listCategories(),
        ]);
        if (cancelled) return;
        setProvinces(provinceRes.items);
        setCategories(categoryRes.items);

        // 加载全部城市（约 300 条，一次拉完比分页更简单）
        const cityRes = await listCities({ page: 1, page_size: 100 });
        if (cancelled) return;
        setCities(cityRes.items);

        if (isEdit && attractionId) {
          const [detail] = await Promise.all([getAttraction(attractionId)]);
          if (cancelled) return;
          form.setFieldsValue({
            name: detail.name,
            province_id:
              cityRes.items.find((c) => c.id === detail.city_id)?.parent_id ?? undefined,
            city_id: detail.city_id,
            category_ids: detail.category_ids,
            summary: detail.summary ?? undefined,
            image_urls: detail.image_urls ?? null,
            ticket_price: detail.ticket_price ? Number(detail.ticket_price) : undefined,
            base_popularity: Number(detail.base_popularity),
            opening_hours: detail.opening_hours as Record<string, string> | null,
            visit_duration_minutes: detail.visit_duration_minutes ?? undefined,
            best_seasons: detail.best_seasons ?? [],
            is_published: detail.is_published,
          });
        } else {
          form.resetFields();
          form.setFieldsValue({ is_published: true, base_popularity: 50 });
        }
      } catch {
        if (!cancelled) message.error('加载表单数据失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
    // form / message 是稳定引用，不需加入依赖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, attractionId, isEdit]);

  const handleOk = async () => {
    let values: FormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }

    setSubmitting(true);
    try {
      const payload: AttractionPayload = {
        name: values.name.trim(),
        city_id: values.city_id,
        summary: values.summary?.trim() || null,
        image_urls: values.image_urls?.length ? values.image_urls : null,
        ticket_price: values.ticket_price != null ? String(values.ticket_price) : null,
        base_popularity:
          values.base_popularity != null ? String(values.base_popularity) : undefined,
        // 开放时间直接以 JSONB 结构提交（{mon: "09:00-17:00", note: "..."}）
        opening_hours: values.opening_hours ?? null,
        visit_duration_minutes: values.visit_duration_minutes ?? null,
        best_seasons: values.best_seasons?.length ? values.best_seasons : null,
        is_published: values.is_published ?? true,
        category_ids: values.category_ids ?? [],
      };

      if (isEdit && attractionId) {
        await updateAttraction(attractionId, payload);
        message.success('景点已更新');
      } else {
        await createAttraction(payload);
        message.success('景点已创建');
      }
      onSuccess();
    } catch (error) {
      // **保留表单状态**，用户修正后可重试
      message.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title={isEdit ? '编辑景点' : '新增景点'}
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={submitting}
      okText="保存"
      cancelText="取消"
      width={720}
      destroyOnClose={false}
    >
      <Form form={form} layout="vertical" requiredMark={false} disabled={loading}>
        <Form.Item
          name="name"
          label="景点名称"
          rules={[
            { required: true, message: '请输入景点名称' },
            { max: 100, message: '最多 100 字符' },
          ]}
        >
          <Input placeholder="如：故宫博物院" maxLength={100} />
        </Form.Item>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="province_id" label="省份">
              <Select
                allowClear
                placeholder="选择省份"
                options={provinces.map((p) => ({ label: p.name, value: p.id }))}
                onChange={() => form.setFieldValue('city_id', undefined)}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="city_id"
              label="城市"
              rules={[{ required: true, message: '请选择城市' }]}
            >
              <Select
                showSearch
                placeholder="选择城市"
                options={cityOptions}
                optionFilterProp="label"
              />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item
          name="category_ids"
          label="分类"
          extra="可多选；保存时整体替换该景点的分类"
          rules={[{ type: 'array', max: 10, message: '最多 10 个分类' }]}
        >
          <Select
            mode="multiple"
            placeholder="选择分类"
            options={categories.map((c) => ({
              label: `${c.name}${c.category_type === 'level' ? '（等级）' : ''}`,
              value: c.id,
            }))}
            optionFilterProp="label"
          />
        </Form.Item>

        <Form.Item name="summary" label="简介" rules={[{ max: 200, message: '最多 200 字符' }]}>
          <Input.TextArea rows={2} placeholder="一句话描述" maxLength={200} showCount />
        </Form.Item>

        <Form.Item name="image_urls" label="图片">
          <ImageUrlsField />
        </Form.Item>

        <Row gutter={16}>
          <Col span={8}>
            <Form.Item name="ticket_price" label="门票价格（元）">
              <InputNumber min={0} precision={2} style={{ width: '100%' }} placeholder="0.00" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item
              name="base_popularity"
              label="基础热度"
              extra="0-100，运营配置"
              rules={[{ type: 'number', min: 0, max: 100 }]}
            >
              <InputNumber min={0} max={100} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="visit_duration_minutes" label="建议游玩（分钟）">
              <InputNumber min={1} style={{ width: '100%' }} placeholder="如 120" />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item name="opening_hours" label="开放时间">
          <OpeningHoursField />
        </Form.Item>

        <Form.Item name="best_seasons" label="最佳季节">
          <Select
            mode="multiple"
            placeholder="可多选"
            options={SEASON_OPTIONS.map((s) => ({ label: s, value: s }))}
          />
        </Form.Item>

        <Form.Item name="is_published" label="上架状态" valuePropName="checked">
          <Switch checkedChildren="已上架" unCheckedChildren="已下架" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/** JSONB → 展示文本。兼容旧数据的多种结构 */
export type { Attraction };
