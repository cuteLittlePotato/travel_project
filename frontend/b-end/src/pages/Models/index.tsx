/**
 * B 端模型管理页（M12-T09，API §10.1 ~ §10.11，原型 `prototype/b-end/models.html`）。
 *
 * 原型是**卡片网格**而非表格：模型数量通常在 10 个以内，一屏能看全，
 * 卡片比表格更能承载「类别 + 地址 + 上下文 + 描述」这类异构信息。
 *
 * 当前页面不含「测试」（连通性测试）入口——那是 M12-T10，
 * 依赖 M12-T05 的后端接口，而 T05 阻塞在 M06-T03 上。
 */
import { useMemo, useState } from 'react';
import {
  App,
  Badge,
  Button,
  Card,
  Empty,
  Input,
  Popconfirm,
  Segmented,
  Skeleton,
  Space,
  Switch,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  StarFilled,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ModelModal } from './ModelModal';
import { ALL_CATEGORY, CATEGORY_META, type CategoryFilter } from './constants';
import {
  deleteModel,
  listModelCategories,
  listModels,
  setModelDefault,
  setModelStatus,
  type Model,
  type ModelCategory,
} from '@/services/model';

const PAGE_SIZE = 100;

export default function ModelsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [activeCategory, setActiveCategory] = useState<CategoryFilter>(ALL_CATEGORY);
  const [keyword, setKeyword] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Model | undefined>();

  const categoriesQuery = useQuery({
    queryKey: ['model-categories'],
    queryFn: listModelCategories,
    staleTime: 30 * 60 * 1000, // 固定枚举，半小时内不必重取
  });

  const modelsQuery = useQuery({
    queryKey: ['models'],
    queryFn: () => listModels({ page: 1, page_size: PAGE_SIZE }),
  });

  const allModels = modelsQuery.data?.items ?? [];

  /** 按类别过滤 + 关键词过滤（前端过滤——数据量小，避免每次输入都请求） */
  const visibleModels = useMemo(() => {
    const lower = keyword.trim().toLowerCase();
    return allModels.filter((model) => {
      if (activeCategory !== ALL_CATEGORY && model.category !== activeCategory) {
        return false;
      }
      if (!lower) return true;
      return (
        model.name.toLowerCase().includes(lower) ||
        model.model_code.toLowerCase().includes(lower)
      );
    });
  }, [allModels, activeCategory, keyword]);

  /** Tab 上的数量：始终基于全量，不随关键词变化 */
  const counts = useMemo(() => {
    const result: Record<string, number> = { [ALL_CATEGORY]: allModels.length };
    for (const model of allModels) {
      result[model.category] = (result[model.category] ?? 0) + 1;
    }
    return result;
  }, [allModels]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['models'] });
  };

  const statusMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      setModelStatus(id, enabled),
    onSuccess: (_, { enabled }) => {
      message.success(enabled ? '模型已启用' : '模型已禁用');
      invalidate();
    },
    // 22003 默认模型不能禁用 / 22004 被知识库引用
    onError: (error: Error) => message.error(error.message || '操作失败'),
  });

  const defaultMutation = useMutation({
    mutationFn: setModelDefault,
    onSuccess: () => {
      message.success('已设为该类别默认模型');
      invalidate();
    },
    // 22005 模型未启用不能设为默认
    onError: (error: Error) => message.error(error.message || '设置失败'),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteModel,
    onSuccess: () => {
      message.success('模型已删除');
      invalidate();
    },
    // 22003 默认不能删 / 22006 被知识库引用
    onError: (error: Error) => message.error(error.message || '删除失败'),
  });

  const categoryOptions = categoriesQuery.data?.items ?? [];

  const segmentedOptions = [
    { label: `全部 (${counts[ALL_CATEGORY] ?? 0})`, value: ALL_CATEGORY },
    ...categoryOptions.map((item) => ({
      label: `${item.name} (${counts[item.code] ?? 0})`,
      value: item.code,
    })),
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        模型管理
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginTop: -8 }}>
        统一 OpenAI 兼容接口。类别为固定枚举，注册后不可修改；每类别最多一个默认模型。
      </Typography.Paragraph>

      <Space style={{ marginBottom: 16 }} wrap>
        <Segmented<CategoryFilter>
          value={activeCategory}
          onChange={setActiveCategory}
          options={segmentedOptions}
        />
        <Input.Search
          allowClear
          placeholder="搜索模型名称..."
          style={{ width: 240 }}
          onChange={(event) => setKeyword(event.target.value)}
          onSearch={setKeyword}
        />
        <Button icon={<ReloadOutlined />} onClick={() => void modelsQuery.refetch()}>
          刷新
        </Button>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            setEditing(undefined);
            setModalOpen(true);
          }}
        >
          注册模型
        </Button>
      </Space>

      {modelsQuery.isLoading ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : visibleModels.length === 0 ? (
        <Empty
          description={
            allModels.length === 0
              ? '暂无模型，点击右上角「注册模型」添加第一个'
              : '当前筛选条件下没有匹配的模型'
          }
        />
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
            gap: 16,
          }}
        >
          {visibleModels.map((model) => (
            <ModelCard
              key={model.id}
              model={model}
              categoryLabel={
                categoryOptions.find((item) => item.code === model.category)?.name ??
                model.category
              }
              onEdit={() => {
                setEditing(model);
                setModalOpen(true);
              }}
              onToggle={(enabled) => statusMutation.mutate({ id: model.id, enabled })}
              onSetDefault={() => defaultMutation.mutate(model.id)}
              onDelete={() => deleteMutation.mutate(model.id)}
            />
          ))}
        </div>
      )}

      <ModelModal
        open={modalOpen}
        initial={editing}
        categoryOptions={categoryOptions}
        defaultCategory={
          activeCategory === ALL_CATEGORY ? undefined : (activeCategory as ModelCategory)
        }
        onCancel={() => setModalOpen(false)}
        onSuccess={() => {
          setModalOpen(false);
          invalidate();
        }}
      />
    </div>
  );
}

/** 单个模型卡片 */
function ModelCard({
  model,
  categoryLabel,
  onEdit,
  onToggle,
  onSetDefault,
  onDelete,
}: {
  model: Model;
  categoryLabel: string;
  onEdit: () => void;
  onToggle: (enabled: boolean) => void;
  onSetDefault: () => void;
  onDelete: () => void;
}) {
  const meta = CATEGORY_META[model.category];

  return (
    <Card
      size="small"
      style={{ opacity: model.is_enabled ? 1 : 0.6 }}
      title={
        <Space>
          <span style={{ fontSize: 18 }}>{meta?.icon}</span>
          <span>
            <div style={{ fontWeight: 600 }}>{model.name}</div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {model.model_code}
            </Typography.Text>
          </span>
        </Space>
      }
      extra={
        <Space size={4}>
          {model.is_default && (
            <Tooltip title="该类别默认模型">
              <Tag color="gold" icon={<StarFilled />}>
                默认
              </Tag>
            </Tooltip>
          )}
          <Badge
            status={model.is_enabled ? 'success' : 'default'}
            text={model.is_enabled ? '已启用' : '已禁用'}
          />
        </Space>
      }
      actions={[
        <Tooltip key="toggle" title={model.is_default ? '默认模型不能直接禁用' : undefined}>
          <Switch
            size="small"
            checked={model.is_enabled}
            checkedChildren="启用"
            unCheckedChildren="禁用"
            onChange={onToggle}
            disabled={model.is_default && model.is_enabled}
          />
        </Tooltip>,
        <Tooltip
          key="default"
          title={model.is_enabled ? '设为该类别默认' : '未启用的模型不能设为默认'}
        >
          <Button
            type="text"
            size="small"
            disabled={!model.is_enabled || model.is_default}
            onClick={onSetDefault}
          >
            设默认
          </Button>
        </Tooltip>,
        <Button key="edit" type="text" size="small" icon={<EditOutlined />} onClick={onEdit}>
          编辑
        </Button>,
        <Popconfirm
          key="delete"
          title="确定删除该模型？"
          description={
            model.is_default
              ? '默认模型不能删除，请先更换默认'
              : '删除后历史调用日志保留'
          }
          okText="删除"
          cancelText="取消"
          okButtonProps={{ danger: true }}
          onConfirm={onDelete}
        >
          <Button type="text" size="small" danger icon={<DeleteOutlined />}>
            删除
          </Button>
        </Popconfirm>,
      ]}
    >
      <Space orientation="vertical" size={6} style={{ width: '100%' }}>
        <InfoRow label="类别">
          <Tag color={meta?.color}>{categoryLabel}</Tag>
        </InfoRow>
        <InfoRow label="接口地址">
          <Typography.Text ellipsis style={{ maxWidth: 200 }} copyable>
            {model.base_url}
          </Typography.Text>
        </InfoRow>
        {model.max_context_tokens != null && (
          <InfoRow label="上下文">
            {model.max_context_tokens.toLocaleString()} tokens
          </InfoRow>
        )}
        <InfoRow label="API Key">
          {model.has_api_key ? (
            <Tag color="green">已配置</Tag>
          ) : (
            <Tag>未配置</Tag>
          )}
        </InfoRow>
        {model.description && (
          <InfoRow label="描述">{model.description}</InfoRow>
        )}
      </Space>
    </Card>
  );
}

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: 13 }}>
      <span style={{ color: '#8c8c8c', flexShrink: 0, minWidth: 56 }}>{label}</span>
      <span style={{ flex: 1, minWidth: 0 }}>{children}</span>
    </div>
  );
}
