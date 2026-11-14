/**
 * B 端景点分类管理页（M11-T14，API §12.9 ~ §12.12）。
 *
 * 分类分两类，语义不同，用 Tab 分组展示（DoD：按 theme/level 分组）：
 *   - `theme` 主题分类：历史人文、自然风光…… C 端筛选项
 *   - `level` 等级分类：5A、4A…… 景区评级
 */
import { useState } from 'react';
import {
  App,
  Button,
  Popconfirm,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { CategoryModal } from './CategoryModal';
import {
  CATEGORY_TYPE_HINT,
  CATEGORY_TYPE_LABEL,
  type CategoryType,
} from './constants';
import { deleteCategory, listCategories, type Category } from '@/services/catalog';

export { CATEGORY_TYPE_LABEL };
export type { CategoryType };

/** 单个分类类型的表格（Tab 内容） */
function CategoryTable({
  categoryType,
  categories,
  loading,
  onCreate,
  onEdit,
}: {
  categoryType: CategoryType;
  categories: Category[];
  loading: boolean;
  onCreate: () => void;
  onEdit: (category: Category) => void;
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const deleteMutation = useMutation({
    mutationFn: deleteCategory,
    onSuccess: () => {
      message.success('分类已删除');
      void queryClient.invalidateQueries({ queryKey: ['categories'] });
    },
    // 有景点关联时后端返回 21005（HTTP 409）
    onError: (error: Error) => message.error(error.message || '删除失败'),
  });

  const columns: ColumnsType<Category> = [
    {
      title: '分类名称',
      dataIndex: 'name',
      width: 220,
      render: (name: string) => <Typography.Text strong>{name}</Typography.Text>,
    },
    {
      title: '描述',
      dataIndex: 'description',
      render: (description: string | null) => description || '—',
    },
    {
      title: '景点数',
      dataIndex: 'attraction_count',
      width: 110,
      render: (count: number | undefined) => (
        <Tag color={(count ?? 0) > 0 ? 'blue' : 'default'}>{count ?? 0}</Tag>
      ),
    },
    { title: '排序', dataIndex: 'sort_weight', width: 90 },
    {
      title: '操作',
      key: 'actions',
      width: 130,
      render: (_, record) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => onEdit(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定删除该分类？"
            description={
              (record.attraction_count ?? 0) > 0
                ? `已有 ${record.attraction_count} 个景点使用此分类，删除会被拒绝`
                : undefined
            }
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => deleteMutation.mutate(record.id)}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <Typography.Text type="secondary">{CATEGORY_TYPE_HINT[categoryType]}</Typography.Text>
        <Button type="primary" icon={<PlusOutlined />} onClick={onCreate}>
          新增{CATEGORY_TYPE_LABEL[categoryType]}
        </Button>
      </Space>

      <Table<Category>
        rowKey="id"
        columns={columns}
        dataSource={categories}
        loading={loading}
        pagination={false}
      />
    </div>
  );
}

export default function CategoriesPage() {
  const queryClient = useQueryClient();

  const [activeType, setActiveType] = useState<CategoryType>('theme');
  const [modalOpen, setModalOpen] = useState(false);
  const [modalType, setModalType] = useState<CategoryType>('theme');
  const [editing, setEditing] = useState<Category | undefined>();

  const categoriesQuery = useQuery({
    queryKey: ['categories'],
    queryFn: () => listCategories(),
  });

  const all = categoriesQuery.data?.items ?? [];
  const grouped: Record<CategoryType, Category[]> = {
    theme: all.filter((item) => item.category_type === 'theme'),
    level: all.filter((item) => item.category_type === 'level'),
  };

  const openCreate = (type: CategoryType) => {
    setModalType(type);
    setEditing(undefined);
    setModalOpen(true);
  };

  const openEdit = (type: CategoryType, category: Category) => {
    setModalType(type);
    setEditing(category);
    setModalOpen(true);
  };

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        景点分类管理
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginTop: -8 }}>
        分类是 C 端景点筛选的核心维度。删除前需先解除景点的分类关联。
      </Typography.Paragraph>

      <Space style={{ marginBottom: 8 }}>
        <Button icon={<ReloadOutlined />} onClick={() => void categoriesQuery.refetch()}>
          刷新
        </Button>
      </Space>

      <Tabs
        activeKey={activeType}
        onChange={(key) => setActiveType(key as CategoryType)}
        items={(['theme', 'level'] as const).map((type) => ({
          key: type,
          label: (
            <Tooltip title={CATEGORY_TYPE_HINT[type]}>
              <span>
                {CATEGORY_TYPE_LABEL[type]}（{grouped[type].length}）
              </span>
            </Tooltip>
          ),
          children: (
            <CategoryTable
              categoryType={type}
              categories={grouped[type]}
              loading={categoriesQuery.isLoading}
              onCreate={() => openCreate(type)}
              onEdit={(category) => openEdit(type, category)}
            />
          ),
        }))}
      />

      <CategoryModal
        open={modalOpen}
        categoryType={modalType}
        parentOptions={grouped[modalType]}
        initial={editing}
        onCancel={() => setModalOpen(false)}
        onSuccess={() => {
          setModalOpen(false);
          void queryClient.invalidateQueries({ queryKey: ['categories'] });
        }}
      />
    </div>
  );
}
