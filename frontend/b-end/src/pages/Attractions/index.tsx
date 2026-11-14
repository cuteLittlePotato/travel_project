/**
 * B 端景点管理页（M11-T11）。
 *
 * 布局与原型 `prototype/b-end/attractions.html` 一致：
 * 搜索框 + 分类筛选 + 表格（9 列）+ 分页 + 编辑/删除操作。
 *
 * 删除有引用的景点时，后端返回 409（21007），前端原样展示后端 message。
 */
import { useState } from 'react';
import {
  App,
  Button,
  Image,
  Input,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { AttractionModal } from './AttractionModal';
import {
  deleteAttraction,
  listAttractions,
  listCategories,
  type Attraction,
} from '@/services/catalog';

const PAGE_SIZE = 10;

export default function AttractionsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [keyword, setKeyword] = useState('');
  const [categoryId, setCategoryId] = useState<string | undefined>();
  const [isPublished, setIsPublished] = useState<boolean | undefined>();
  const [page, setPage] = useState(1);

  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | undefined>();

  // ---------- 数据 ----------
  const listQuery = useQuery({
    queryKey: ['attractions', { keyword, categoryId, isPublished, page }],
    queryFn: () =>
      listAttractions({
        keyword: keyword || undefined,
        category_id: categoryId,
        is_published: isPublished,
        page,
        page_size: PAGE_SIZE,
      }),
  });

  const categoriesQuery = useQuery({
    queryKey: ['categories'],
    queryFn: () => listCategories(),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteAttraction,
    onSuccess: () => {
      message.success('景点已删除');
      void queryClient.invalidateQueries({ queryKey: ['attractions'] });
    },
    onError: (error: Error) => {
      // 后端 409（有引用）的 message 直接展示——如「该景点已被引用（footprint 3 条），无法删除」
      message.error(error.message || '删除失败');
    },
  });

  // ---------- 列定义（与原型 9 列一致） ----------
  const columns: ColumnsType<Attraction> = [
    {
      title: 'ID',
      dataIndex: 'id',
      width: 100,
      render: (id: string) => (
        <Tooltip title={id}>
          <Typography.Text copyable={{ text: id }} style={{ fontSize: 12 }}>
            {id.slice(0, 8)}
          </Typography.Text>
        </Tooltip>
      ),
    },
    {
      title: '图片',
      dataIndex: 'cover_image_url',
      width: 90,
      render: (url: string | null) =>
        url ? (
          <Image src={url} alt="" width={56} height={40} style={{ objectFit: 'cover', borderRadius: 4 }} />
        ) : (
          <div
            style={{
              width: 56,
              height: 40,
              background: '#f5f5f5',
              borderRadius: 4,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#bfbfbf',
              fontSize: 12,
            }}
          >
            无图
          </div>
        ),
    },
    {
      title: '景点名称',
      dataIndex: 'name',
      width: 200,
      render: (name: string, record) => (
        <Tooltip title={record.summary ?? undefined}>
          <Typography.Text strong>{name}</Typography.Text>
        </Tooltip>
      ),
    },
    {
      title: '城市',
      dataIndex: 'city_name',
      width: 120,
      render: (city: string | null) => city ?? '—',
    },
    {
      title: '分类',
      dataIndex: 'categories',
      width: 200,
      render: (categories: string[]) =>
        categories.length > 0 ? (
          <Space size={4} wrap>
            {categories.map((c) => (
              <Tag key={c} color="blue" style={{ marginBottom: 4 }}>
                {c}
              </Tag>
            ))}
          </Space>
        ) : (
          <Typography.Text type="secondary">未分类</Typography.Text>
        ),
    },
    {
      title: '门票价格',
      dataIndex: 'ticket_price',
      width: 100,
      render: (price: string | null) =>
        price ? `¥${Number(price).toFixed(2)}` : '—',
    },
    {
      title: '热度',
      dataIndex: 'final_popularity',
      width: 90,
      sorter: (a, b) =>
        Number(a.final_popularity ?? a.base_popularity) -
        Number(b.final_popularity ?? b.base_popularity),
      render: (value: string | null, record) => {
        const score = Number(value ?? record.base_popularity);
        const color = score >= 80 ? '#52c41a' : score >= 50 ? '#1677ff' : '#8c8c8c';
        return <span style={{ color, fontWeight: 600 }}>{score.toFixed(1)}</span>;
      },
    },
    {
      title: '状态',
      dataIndex: 'is_published',
      width: 90,
      render: (published: boolean) =>
        published ? <Tag color="green">已上架</Tag> : <Tag>已下架</Tag>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 140,
      fixed: 'right',
      render: (_, record) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => {
              setEditingId(record.id);
              setModalOpen(true);
            }}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定删除该景点？"
            description="若已被足迹或行程引用，将无法删除"
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
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        景点管理
      </Typography.Title>

      {/* 筛选栏 */}
      <Space style={{ marginBottom: 16 }} wrap>
        <Input.Search
          placeholder="搜索景点名称、城市..."
          allowClear
          style={{ width: 260 }}
          onSearch={(value) => {
            setKeyword(value);
            setPage(1);
          }}
        />
        <Select
          allowClear
          placeholder="全部分类"
          style={{ width: 180 }}
          value={categoryId}
          onChange={(value) => {
            setCategoryId(value);
            setPage(1);
          }}
          options={(categoriesQuery.data?.items ?? []).map((c) => ({
            label: c.name,
            value: c.id,
          }))}
        />
        <Select
          allowClear
          placeholder="全部状态"
          style={{ width: 120 }}
          value={isPublished}
          onChange={(value) => {
            setIsPublished(value);
            setPage(1);
          }}
          options={[
            { label: '已上架', value: true },
            { label: '已下架', value: false },
          ]}
        />
        <Button icon={<ReloadOutlined />} onClick={() => void listQuery.refetch()}>
          刷新
        </Button>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            setEditingId(undefined);
            setModalOpen(true);
          }}
        >
          新增景点
        </Button>
      </Space>

      <Table<Attraction>
        rowKey="id"
        columns={columns}
        dataSource={listQuery.data?.items ?? []}
        loading={listQuery.isLoading}
        scroll={{ x: 1200 }}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total: listQuery.data?.total ?? 0,
          showSizeChanger: false,
          showTotal: (total) => `共 ${total} 条`,
          onChange: setPage,
        }}
      />

      <AttractionModal
        open={modalOpen}
        attractionId={editingId}
        onCancel={() => setModalOpen(false)}
        onSuccess={() => {
          setModalOpen(false);
          void queryClient.invalidateQueries({ queryKey: ['attractions'] });
        }}
      />
    </div>
  );
}
