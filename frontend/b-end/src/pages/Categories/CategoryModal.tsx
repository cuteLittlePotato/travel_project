/**
 * 景点分类的创建 / 编辑模态框（M11-T14，API §12.10 ~ §12.11）。
 *
 * 编辑时 `category_type` 不可修改（后端 CategoryUpdate 已排除该字段）——
 * 改类型会让已有景点关联的语义错乱。
 */
import { useEffect, useState } from 'react';
import { App, Form, Input, InputNumber, Modal, Select } from 'antd';

import {
  createCategory,
  updateCategory,
  type Category,
  type CategoryCreatePayload,
  type CategoryPayload,
} from '@/services/catalog';
import { CATEGORY_TYPE_LABEL, type CategoryType } from './constants';

export interface CategoryFormValues {
  name: string;
  parent_id?: string | null;
  description?: string;
  sort_weight?: number;
}

export interface CategoryModalProps {
  open: boolean;
  categoryType: CategoryType;
  /** 编辑时传入；`parent_id` 由它带入 */
  initial?: Category;
  /** 供「上级分类」下拉使用的同类型分类 */
  parentOptions?: Category[];
  onCancel: () => void;
  onSuccess: () => void;
}

export function CategoryModal({
  open,
  categoryType,
  initial,
  parentOptions = [],
  onCancel,
  onSuccess,
}: CategoryModalProps) {
  const [form] = Form.useForm<CategoryFormValues>();
  const { message } = App.useApp();
  const [submitting, setSubmitting] = useState(false);

  const isEdit = Boolean(initial);

  useEffect(() => {
    if (!open) return;
    if (initial) {
      form.setFieldsValue({
        name: initial.name,
        parent_id: initial.parent_id ?? undefined,
        description: initial.description ?? undefined,
        sort_weight: initial.sort_weight,
      });
    } else {
      form.resetFields();
      form.setFieldsValue({ sort_weight: 0 });
    }
  }, [open, initial, form]);

  const handleOk = async () => {
    let values: CategoryFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }

    setSubmitting(true);
    try {
      const payload: CategoryPayload = {
        name: values.name.trim(),
        description: values.description?.trim() || null,
        sort_weight: values.sort_weight ?? 0,
      };

      if (isEdit && initial) {
        await updateCategory(initial.id, payload);
        message.success('分类已更新');
      } else {
        const createPayload: CategoryCreatePayload = {
          ...payload,
          category_type: categoryType,
          parent_id: values.parent_id ?? null,
        };
        await createCategory(createPayload);
        message.success('分类已创建');
      }
      onSuccess();
    } catch (error) {
      // 同类型下名称重复 → 21004（HTTP 409）
      message.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setSubmitting(false);
    }
  };

  // 编辑时排除自己，避免把自己设为父级
  const availableParents = parentOptions.filter((item) => item.id !== initial?.id);

  return (
    <Modal
      open={open}
      title={
        isEdit
          ? `编辑${CATEGORY_TYPE_LABEL[categoryType]}`
          : `新增${CATEGORY_TYPE_LABEL[categoryType]}`
      }
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={submitting}
      okText="保存"
      cancelText="取消"
      width={520}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item
          name="name"
          label="分类名称"
          rules={[
            { required: true, message: '请输入分类名称' },
            { max: 50, message: '最多 50 字符' },
          ]}
        >
          <Input placeholder={categoryType === 'level' ? '如：5A' : '如：历史人文'} maxLength={50} />
        </Form.Item>

        <Form.Item
          name="parent_id"
          label="上级分类"
          extra={isEdit ? '分类的层级关系不支持修改' : '留空即为一级分类，支持二级'}
        >
          <Select
            allowClear
            disabled={isEdit}
            placeholder="不设上级（一级分类）"
            options={availableParents.map((item) => ({ label: item.name, value: item.id }))}
          />
        </Form.Item>

        <Form.Item name="sort_weight" label="排序权重" extra="数值越大越靠前">
          <InputNumber style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item name="description" label="描述">
          <Input.TextArea rows={2} maxLength={200} showCount />
        </Form.Item>
      </Form>
    </Modal>
  );
}
