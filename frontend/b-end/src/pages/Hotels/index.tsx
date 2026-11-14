/**
 * B 端酒店管理页（M11-T12）。
 *
 * 布局与原型 `prototype/b-end/hotels.html` 一致：
 * 9 列表格（ID/图片/酒店名称/星级/城市/价格区间/房型/状态/操作）。
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

import { HotelModal } from './HotelModal';
import { deleteHotel, listHotels, type Hotel } from '@/services/catalog';

const PAGE_SIZE = 10;

/** 星级 → 展示文案 */
const STAR_LABEL: Record<string, string> = {
  five: '五星级',
  four: '四星级',
  three: '三星级',
  two: '二星级',
  one: '一星级',
  boutique: '精品酒店',
};

export default function HotelsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [keyword, setKeyword] = useState('');
  const [isPublished, setIsPublished] = useState<boolean | undefined>();
  const [page, setPage] = useState(1);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | undefined>();

  const listQuery = useQuery({
    queryKey: ['hotels', { keyword, isPublished, page }],
    queryFn: () =>
      listHotels({
        keyword: keyword || undefined,
        is_published: isPublished,
        page,
        page_size: PAGE_SIZE,
      }),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteHotel,
    onSuccess: () => {
      message.success('酒店已删除');
      void queryClient.invalidateQueries({ queryKey: ['hotels'] });
    },
    onError: (error: Error) => message.error(error.message || '删除失败'),
  });

  const columns: ColumnsType<Hotel> = [
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
      // 酒店列表接口不返回 cover_image_url，用占位（后续接口扩展后接入）
      render: () => <HotelThumbnail src={null} />,
    },
    {
      title: '酒店名称',
      dataIndex: 'name',
      width: 200,
      render: (name: string) => <Typography.Text strong>{name}</Typography.Text>,
    },
    {
      title: '星级',
      dataIndex: 'star_level',
      width: 110,
      render: (star: string | null) =>
        star ? <Tag color="gold">{STAR_LABEL[star] ?? star}</Tag> : '—',
    },
    {
      title: '城市',
      dataIndex: 'city_name',
      width: 120,
      render: (city: string | null) => city ?? '—',
    },
    {
      title: '价格区间',
      dataIndex: 'min_price',
      width: 150,
      render: (minPrice: string | null, record) => {
        if (!minPrice && !record.max_price) return '—';
        const min = minPrice ? Number(minPrice).toFixed(0) : '?';
        const max = record.max_price ? Number(record.max_price).toFixed(0) : '?';
        return `¥${min} - ¥${max}`;
      },
    },
    {
      title: '房型',
      dataIndex: 'room_types',
      width: 160,
      render: () => <Typography.Text type="secondary">—</Typography.Text>,
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
            title="确定删除该酒店？"
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
        酒店管理
      </Typography.Title>

      <Space style={{ marginBottom: 16 }} wrap>
        <Input.Search
          placeholder="搜索酒店名称..."
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
          新增酒店
        </Button>
      </Space>

      <Table<Hotel>
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

      <HotelModal
        open={modalOpen}
        hotelId={editingId}
        onCancel={() => setModalOpen(false)}
        onSuccess={() => {
          setModalOpen(false);
          void queryClient.invalidateQueries({ queryKey: ['hotels'] });
        }}
      />
    </div>
  );
}

/** 80×80 缩略图，加载失败降级为占位 */
export function HotelThumbnail({ src }: { src: string | null }) {
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
    />
  );
}
