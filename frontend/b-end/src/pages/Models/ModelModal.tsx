/**
 * 注册 / 编辑模型模态框（M12-T09，API §10.2 / §10.4）。
 *
 * 两条与后端一致的约束：
 *   - **类别不可改**：编辑时 Select 禁用。改类别会让该模型已有的调用日志、
 *     默认配置、调用方代码全部失去意义（后端返回 22002）。
 *   - **API Key 三态**：编辑时不填 = 保持原值，填了 = 替换。
 *     后端不回传密钥，所以这里用「留空即不变」的提示而不是回显掩码。
 */
import { useEffect, useState } from 'react';
import {
  App,
  Alert,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Switch,
  Typography,
} from 'antd';

import {
  createModel,
  updateModel,
  type Model,
  type ModelCategory,
  type ModelCategoryOption,
  type ModelPayload,
} from '@/services/model';

/** 文本类类别需要填上下文长度（与后端 TEXT_CATEGORIES 一致） */
const TEXT_CATEGORIES: readonly ModelCategory[] = ['chat', 'vision'];

export interface ModelFormValues {
  name: string;
  category: ModelCategory;
  model_code: string;
  base_url: string;
  api_key?: string;
  max_context_tokens?: number;
  max_output_tokens?: number;
  timeout_seconds?: number;
  concurrency_limit?: number;
  price_input?: number;
  price_output?: number;
  description?: string;
  is_default?: boolean;
}

export interface ModelModalProps {
  open: boolean;
  initial?: Model;
  categoryOptions: ModelCategoryOption[];
  /** 默认选中的类别（从当前筛选 Tab 带入） */
  defaultCategory?: ModelCategory;
  onCancel: () => void;
  onSuccess: () => void;
}

export function ModelModal({
  open,
  initial,
  categoryOptions,
  defaultCategory,
  onCancel,
  onSuccess,
}: ModelModalProps) {
  const [form] = Form.useForm<ModelFormValues>();
  const { message } = App.useApp();
  const [submitting, setSubmitting] = useState(false);

  const isEdit = Boolean(initial);
  // 监听类别以决定「上下文长度」是否必填
  const category = Form.useWatch('category', form);
  // 监听「设为默认」以展示影响提示
  const isDefault = Form.useWatch('is_default', form);

  useEffect(() => {
    if (!open) return;

    if (initial) {
      form.setFieldsValue({
        name: initial.name,
        category: initial.category,
        model_code: initial.model_code,
        base_url: initial.base_url,
        api_key: undefined,
        max_context_tokens: initial.max_context_tokens ?? undefined,
        max_output_tokens: initial.max_output_tokens ?? undefined,
        timeout_seconds: initial.timeout_seconds,
        concurrency_limit: initial.concurrency_limit ?? undefined,
        price_input: initial.price_input ? Number(initial.price_input) : undefined,
        price_output: initial.price_output ? Number(initial.price_output) : undefined,
        description: initial.description ?? undefined,
        is_default: initial.is_default,
      });
    } else {
      form.resetFields();
      form.setFieldsValue({
        timeout_seconds: 60,
        is_default: false,
        category: defaultCategory ?? 'chat',
      });
    }
  }, [open, initial, defaultCategory, form]);

  const requiresContext =
    category !== undefined && TEXT_CATEGORIES.includes(category);

  const handleOk = async () => {
    let values: ModelFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }

    setSubmitting(true);
    try {
      const payload: ModelPayload = {
        name: values.name.trim(),
        category: values.category,
        model_code: values.model_code.trim(),
        base_url: values.base_url.trim(),
        max_context_tokens: values.max_context_tokens ?? null,
        max_output_tokens: values.max_output_tokens ?? null,
        timeout_seconds: values.timeout_seconds ?? 60,
        concurrency_limit: values.concurrency_limit ?? null,
        price_input: values.price_input != null ? String(values.price_input) : null,
        price_output: values.price_output != null ? String(values.price_output) : null,
        description: values.description?.trim() || null,
        is_default: values.is_default ?? false,
      };

      // api_key 三态：编辑时留空表示不变，因此只在填了值时才传
      if (values.api_key) {
        payload.api_key = values.api_key;
      } else if (!isEdit) {
        payload.api_key = null;
      }

      if (isEdit && initial) {
        await updateModel(initial.id, payload);
        message.success('模型已更新');
      } else {
        await createModel(payload);
        message.success('模型已注册');
      }
      onSuccess();
    } catch (error) {
      // 22001 重复 / 22002 类别不可改 等业务错误由后端返回
      message.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title={isEdit ? '编辑模型' : '注册模型'}
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={submitting}
      okText="保存"
      cancelText="取消"
      width={680}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        <Typography.Text type="secondary" style={{ fontSize: 13 }}>
          基础信息
        </Typography.Text>

        <Row gutter={16} style={{ marginTop: 8 }}>
          <Col span={12}>
            <Form.Item
              name="name"
              label="显示名称"
              rules={[
                { required: true, message: '请输入显示名称' },
                { max: 100, message: '最多 100 字符' },
              ]}
            >
              <Input placeholder="如：DeepSeek-V3" maxLength={100} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="category"
              label="模型类别"
              rules={[{ required: true, message: '请选择模型类别' }]}
              extra={isEdit ? '类别注册后不可修改' : undefined}
            >
              <Select
                disabled={isEdit}
                placeholder="选择类别"
                options={categoryOptions.map((item) => ({
                  label: item.name,
                  value: item.code,
                }))}
              />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item
          name="model_code"
          label="调用模型 ID"
          rules={[
            { required: true, message: '请输入调用模型 ID' },
            { max: 100, message: '最多 100 字符' },
          ]}
        >
          <Input placeholder="如：deepseek-chat" maxLength={100} />
        </Form.Item>

        <Form.Item
          name="base_url"
          label="接口地址"
          rules={[
            { required: true, message: '请输入接口地址' },
            {
              validator: (_, value?: string) => {
                if (!value) return Promise.resolve();
                if (!/^https?:\/\//.test(value)) {
                  return Promise.reject(new Error('必须以 http:// 或 https:// 开头'));
                }
                return Promise.resolve();
              },
            },
          ]}
        >
          <Input placeholder="https://api.example.com/v1" maxLength={500} />
        </Form.Item>

        <Form.Item
          name="api_key"
          label="API Key"
          extra={
            isEdit
              ? initial?.has_api_key
                ? '留空表示保持原值；填写则覆盖'
                : '当前未配置密钥，填写后生效'
              : '明文传输，服务端加密存储'
          }
        >
          <Input.Password placeholder="sk-..." autoComplete="new-password" maxLength={500} />
        </Form.Item>

        <Typography.Text type="secondary" style={{ fontSize: 13 }}>
          模型参数
        </Typography.Text>

        <Row gutter={16} style={{ marginTop: 8 }}>
          <Col span={12}>
            <Form.Item
              name="max_context_tokens"
              label="最大上下文"
              rules={
                requiresContext
                  ? [{ required: true, message: '文本类模型必须填写上下文长度' }]
                  : []
              }
              extra={requiresContext ? '文本类模型必填' : undefined}
            >
              <InputNumber min={1} style={{ width: '100%' }} placeholder="如：128000" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="max_output_tokens" label="单次最大输出">
              <InputNumber min={1} style={{ width: '100%' }} placeholder="如：4096" />
            </Form.Item>
          </Col>
        </Row>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="timeout_seconds"
              label="超时时间（秒）"
              rules={[{ type: 'number', min: 1, max: 300, message: '需在 1-300 之间' }]}
            >
              <InputNumber min={1} max={300} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="concurrency_limit" label="并发上限">
              <InputNumber min={1} max={1000} style={{ width: '100%' }} placeholder="如：20" />
            </Form.Item>
          </Col>
        </Row>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="price_input" label="输入单价（元/千 token）">
              <InputNumber min={0} step={0.001} style={{ width: '100%' }} placeholder="如：0.001" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="price_output" label="输出单价（元/千 token）">
              <InputNumber min={0} step={0.001} style={{ width: '100%' }} placeholder="如：0.002" />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item name="description" label="描述">
          <Input.TextArea rows={2} maxLength={500} showCount placeholder="备注模型能力特点" />
        </Form.Item>

        <Form.Item name="is_default" label="设为该类别默认" valuePropName="checked">
          <Switch />
        </Form.Item>

        {!!isDefault && (
          <Alert
            type="info"
            showIcon
            message="保存后同类别原有默认模型会被自动取消"
          />
        )}
      </Form>
    </Modal>
  );
}
