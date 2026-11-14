/**
 * B 端餐厅管理页（M11-T12）。
 *
 * 布局与原型 `prototype/b-end/restaurants.html` 一致：
 * 9 列表格（ID/图片/餐厅名称/类型/城市/人均消费/营业时间/状态/操作）。
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

import { RestaurantModal } from './RestaurantModal';
import {
  deleteRestaurant,
  listRestaurants,
  type Restaurant,
} from '@/services/catalog';

const PAGE_SIZE = 10;

/**
 * 把营业时间 JSONB 压缩成一行摘要。
 *
 * 七天完全一致时显示 ``09:00-17:00``（有备注则拼上）；
 * 各天不同时显示「按星期设置」，避免表格里塞七行文字。
 */
function formatBusinessHours(hours: Record<string, string> | null): string {
  if (!hours) return '—';

  const days = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
  const values = days
    .map((d) => hours[d])
    .filter((v): v is string => typeof v === 'string' && v.length > 0);
  const note = typeof hours.note === 'string' ? hours.note : '';

  if (values.length === 0) return note || '—';

  const first = values[0];
  const allSame =
    first !== undefined && values.length === days.length && values.every((v) => v === first);
  if (allSame && first !== undefined) {
    const main = first === 'closed' ? '全天闭店' : first;
    return note ? `${main}（${note}）` : main;
  }

  return note ? `按星期设置（${note}）` : '按星期设置';
}

export default function RestaurantsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [keyword, setKeyword] = useState('');
  const [isPublished, setIsPublished] = useState<boolean | undefined>();
  const [page, setPage] = useState(1);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | undefined>();

  const listQuery = useQuery({
    queryKey: ['restaurants', { keyword, isPublished, page }],
    queryFn: () =>
      listRestaurants({
        keyword: keyword || undefined,
        is_published: isPublished,
        page,
        page_size: PAGE_SIZE,
      }),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteRestaurant,
    onSuccess: () => {
      message.success('餐厅已删除');
      void queryClient.invalidateQueries({ queryKey: ['restaurants'] });
    },
    onError: (error: Error) => message.error(error.message || '删除失败'),
  });

  const columns: ColumnsType<Restaurant> = [
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
      render: (url: string | null) => <Thumbnail src={url} />,
    },
    {
      title: '餐厅名称',
      dataIndex: 'name',
      width: 200,
      render: (name: string) => <Typography.Text strong>{name}</Typography.Text>,
    },
    {
      title: '类型',
      dataIndex: 'cuisine_type',
      width: 110,
      render: (cuisine: string | null) =>
        cuisine ? <Tag color="orange">{cuisine}</Tag> : '—',
    },
    {
      title: '城市',
      dataIndex: 'city_name',
      width: 120,
      render: (city: string | null) => city ?? '—',
    },
    {
      title: '人均消费',
      dataIndex: 'avg_cost',
      width: 110,
      render: (cost: string | null) => (cost ? `¥${Number(cost).toFixed(2)}` : '—'),
    },
    {
      title: '营业时间',
      dataIndex: 'business_hours',
      width: 180,
      render: (hours: Record<string, string> | null) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {formatBusinessHours(hours)}
        </Typography.Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_published',
      width: 90,
      render: (published: boolean) =>
        published ? <Tag color="green">营业中</Tag> : <Tag>已下架</Tag>,
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
            title="确定删除该餐厅？"
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
        餐厅管理
      </Typography.Title>

      <Space style={{ marginBottom: 16 }} wrap>
        <Input.Search
          placeholder="搜索餐厅名称..."
          allowClear
          style={{ width: 260 }}
          onSearch={(value) => {
            setKeyword(value);
            setPage(1);
          }}
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
            { label: '营业中', value: true },
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
          新增餐厅
        </Button>
      </Space>

      <Table<Restaurant>
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

      <RestaurantModal
        open={modalOpen}
        restaurantId={editingId}
        onCancel={() => setModalOpen(false)}
        onSuccess={() => {
          setModalOpen(false);
          void queryClient.invalidateQueries({ queryKey: ['restaurants'] });
        }}
      />
    </div>
  );
}

/** 80×80 缩略图（DoD 要求）。加载失败降级为占位 */
export function Thumbnail({ src }: { src: string | null }) {
  const [failed, setFailed] = useState(false);

  if (!src || failed) {
    return (
      <div
        style={{
          width: 80,
          height: 80,
          background: '#f5f5f5',
          borderRadius: 6,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#bfbfbf',
          fontSize: 12,
        }}
      >
        无图
      </div>
    );
  }

  return (
    <Image
      src={src}
      alt=""
      width={80}
      height={80}
      style={{ objectFit: 'cover', borderRadius: 6 }}
      onError={() => setFailed(true)}
      fallback="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI4MCIgaGVpZ2h0PSI4MCI+PHJlY3Qgd2lkdGg9IjgwIiBoZWlnaHQ9IjgwIiBmaWxsPSIjZjVmNWY1Ii8+PC9zdmc+"
    />
  );
}
