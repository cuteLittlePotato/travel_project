/**
 * 站点配置面板（M15-T10，API §14.12 / §14.13）。
 *
 * 对应原型 `settings.html` 的「基础设置」卡片。
 * **原型的「AI 对话设置」卡片已移除**——AI 模型由 M12 模型管理承担，
 * 任务卡明确要求（DoD 规范检查项）。
 */
import { useEffect } from 'react';
import { App, Button, Card, Form, Input, Spin, Switch, Typography } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  getSiteSettings,
  updateSiteSettings,
  type SiteSettings,
} from '@/services/system';

export function SiteSettingsPanel() {
  const [form] = Form.useForm<SiteSettings>();
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const settingsQuery = useQuery({
    queryKey: ['site-settings'],
    queryFn: getSiteSettings,
  });

  useEffect(() => {
    if (settingsQuery.data) {
      form.setFieldsValue(settingsQuery.data);
    }
  }, [settingsQuery.data, form]);

  const saveMutation = useMutation({
    mutationFn: updateSiteSettings,
    onSuccess: () => {
      message.success('配置已保存');
      void queryClient.invalidateQueries({ queryKey: ['site-settings'] });
    },
    onError: (error: Error) => message.error(error.message || '保存失败'),
  });

  const handleSave = async () => {
    let values: SiteSettings;
    try {
      values = await form.validateFields();
    } catch {
      // 校验失败时 antd 已在表单上标出错误，这里只需终止提交。
      // 不捕获的话会抛未处理的 Promise rejection。
      return;
    }
    saveMutation.mutate(values);
  };

  return (
    <Card
      title="基础设置"
      extra={
        <Button
          type="primary"
          onClick={handleSave}
          loading={saveMutation.isPending}
        >
          保存
        </Button>
      }
    >
      <Spin spinning={settingsQuery.isLoading}>
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item
          name="site_name"
          label="网站名称"
          extra="显示在浏览器标签和页面标题"
          rules={[
            { required: true, message: '请输入网站名称' },
            { max: 100, message: '最多 100 字符' },
          ]}
        >
          <Input placeholder="如：云游坊" maxLength={100} />
        </Form.Item>

        <Form.Item
          name="site_description"
          label="网站描述"
          extra="用于 SEO 优化"
          rules={[{ max: 500, message: '最多 500 字符' }]}
        >
          <Input.TextArea rows={2} maxLength={500} showCount />
        </Form.Item>

        <Form.Item
          name="allow_registration"
          label="允许用户注册"
          extra="关闭后 C 端将不再接受新用户注册"
          valuePropName="checked"
        >
          <Switch checkedChildren="允许" unCheckedChildren="关闭" />
        </Form.Item>

        <Form.Item
          name="allow_content_review"
          label="开启内容审核"
          extra="用户发布的足迹、评分需审核后展示"
          valuePropName="checked"
        >
          <Switch checkedChildren="开启" unCheckedChildren="关闭" />
        </Form.Item>
      </Form>
      </Spin>

      <Typography.Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
        说明：AI 模型配置已移至「模型管理」，此处不再提供。
      </Typography.Paragraph>
    </Card>
  );
}
