/**
 * 省份 / 城市的创建与编辑模态框（M11-T14，API §12.2~§12.3 / §12.6~§12.7）。
 *
 * 省份与城市字段完全一致，只有两点差异：
 *   - 城市的 `parent_id` 必填
 *   - 城市编辑时不允许改上级（后端 RegionUpdate 已排除 parent_id）
 */
import { useEffect } from 'react';
import { App, Col, Form, Input, InputNumber, Modal, Row } from 'antd';
import { useMutation } from '@tanstack/react-query';

import {
  createCity,
  createProvince,
  updateCity,
  updateProvince,
  type CityListItem,
  type ProvinceListItem,
  type RegionPayload,
} from '@/services/catalog';

export type RegionModalMode = 'province' | 'city';

/** 6 位国标行政区划编码（GB/T 2260） */
const REGION_CODE_PATTERN = /^\d{6}$/;

export interface RegionFormValues {
  name: string;
  code: string;
  heat_score?: number;
  sort_weight?: number;
  description?: string;
  cover_image_url?: string;
}

export interface RegionModalProps {
  open: boolean;
  mode: RegionModalMode;
  /** 城市模式下必传，用于提交 parent_id 与标题展示 */
  parentProvince?: ProvinceListItem;
  initial?: ProvinceListItem | CityListItem;
  onCancel: () => void;
  onSuccess: () => void;
}

export function RegionModal({
  open,
  mode,
  parentProvince,
  initial,
  onCancel,
  onSuccess,
}: RegionModalProps) {
  const [form] = Form.useForm<RegionFormValues>();
  const { message } = App.useApp();

  const isEdit = Boolean(initial);
  const isCity = mode === 'city';

  useEffect(() => {
    if (!open) return;
    if (initial) {
      form.setFieldsValue({
        name: initial.name,
        code: initial.code,
        heat_score: Number(initial.heat_score),
        sort_weight: initial.sort_weight,
        description: initial.description ?? undefined,
        cover_image_url: initial.cover_image_url ?? undefined,
      });
    } else {
      form.resetFields();
      form.setFieldsValue({ heat_score: 0, sort_weight: 0 });
    }
  }, [open, initial, form]);

  const mutation = useMutation({
    mutationFn: async (values: RegionFormValues) => {
      const payload: RegionPayload = {
        name: values.name.trim(),
        code: values.code.trim(),
        heat_score: String(values.heat_score ?? 0),
        sort_weight: values.sort_weight ?? 0,
        description: values.description?.trim() || null,
        cover_image_url: values.cover_image_url?.trim() || null,
      };

      if (isEdit && initial) {
        await (isCity ? updateCity(initial.id, payload) : updateProvince(initial.id, payload));
      } else if (isCity) {
        if (!parentProvince) throw new Error('缺少上级省份');
        await createCity({ ...payload, parent_id: parentProvince.id });
      } else {
        await createProvince(payload);
      }
    },
    onSuccess: () => {
      message.success(isEdit ? '已更新' : '已创建');
      onSuccess();
    },
    // 编码重复 21001 / 名称重复等由后端返回，错误信息可直接展示
    onError: (error: Error) => message.error(error.message || '保存失败'),
  });

  const handleOk = async () => {
    let values: RegionFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    mutation.mutate(values);
  };

  const entityLabel = isCity ? '城市' : '省份';
  const title = isEdit
    ? `编辑${entityLabel}`
    : isCity && parentProvince
      ? `在「${parentProvince.name}」下新增城市`
      : `新增${entityLabel}`;

  return (
    <Modal
      open={open}
      title={title}
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={mutation.isPending}
      okText="保存"
      cancelText="取消"
      width={560}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="name"
              label={`${entityLabel}名称`}
              rules={[
                { required: true, message: `请输入${entityLabel}名称` },
                { max: 50, message: '最多 50 字符' },
              ]}
            >
              <Input placeholder={isCity ? '如：杭州市' : '如：浙江省'} maxLength={50} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="code"
              label="行政区划编码"
              extra="6 位国标编码（GB/T 2260）"
              rules={[
                { required: true, message: '请输入行政区划编码' },
                {
                  pattern: REGION_CODE_PATTERN,
                  message: '必须是 6 位数字',
                },
              ]}
            >
              <Input placeholder="如：330000" maxLength={6} />
            </Form.Item>
          </Col>
        </Row>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="heat_score"
              label="热度"
              extra="0 - 100，影响 C 端推荐排序"
              rules={[
                {
                  type: 'number',
                  min: 0,
                  max: 100,
                  message: '热度需在 0 到 100 之间',
                },
              ]}
            >
              <InputNumber min={0} max={100} step={0.1} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="sort_weight" label="排序权重" extra="数值越大越靠前">
              <InputNumber style={{ width: '100%' }} />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item name="cover_image_url" label="封面图 URL">
          <Input placeholder="https://..." maxLength={500} />
        </Form.Item>

        <Form.Item name="description" label="描述">
          <Input.TextArea rows={3} maxLength={1000} showCount />
        </Form.Item>
      </Form>
    </Modal>
  );
}
