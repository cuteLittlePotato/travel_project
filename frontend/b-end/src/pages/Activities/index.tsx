/**
 * B 端活动管理页（M11-T13，API §12.31 ~ §12.36）。
 *
 * 原型中无对应页面（评审 §Q6：前端按设计文档自行设计）。
 *
 * 关键设计（评审 §Q3）：
 *   - **无价格字段**：活动定价差异大，走 `detail_url` 外链
 *   - **无状态字段**：状态由日期实时计算，以徽章展示
 */
import { useState } from 'react';
import {
  App,
  Button,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ActivityModal } from './ActivityModal';
import {
  deleteActivity,
  listActivities,
  setActivityPublished,
  type Activity,
  type ActivityStatus,
  type ActivityType,
} from '@/services/catalog';

const PAGE_SIZE = 10;

const TYPE_LABEL: Record<ActivityType, { text: string; color: string }> = {
  discount: { text: '特惠', color: 'red' },
  festival: { text: '节庆', color: 'orange' },
  exhibition: { text: '展览', color: 'blue' },
  other: { text: '其他', color: 'default' },
};

/** DoD：状态徽章按 upcoming/ongoing/ended 着色 */
export const STATUS_CONFIG: Record<
  ActivityStatus,
  { text: string; color: string }
> = {
  upcoming: { text: '未开始', color: 'blue' },
  ongoing: { text: '进行中', color: 'green' },
  ended: { text: '已结束', color: 'default' },
};

export default function ActivitiesPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [isPublished, setIsPublished] = useState<boolean | undefined>();
  const [page, setPage] = useState(1);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Activity | undefined>();

  const listQuery = useQuery({
    queryKey: ['activities', { isPublished, page }],
    queryFn: () =>
      listActivities({ is_published: isPublished, page, page_size: PAGE_SIZE }),
  });

  const publishMutation = useMutation({
    mutationFn: ({ id, value }: { id: string; value: boolean }) =>
      setActivityPublished(id, value),
    onSuccess: (_, variables) => {
      message.success(variables.value ? '活动已上架' : '活动已下架');
      void queryClient.invalidateQueries({ queryKey: ['activities'] });
    },
    onError: (error: Error) => message.error(error.message || '操作失败'),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteActivity,
    onSuccess: () => {
      message.success('活动已删除');
      void queryClient.invalidateQueries({ queryKey: ['activities'] });
    },
    onError: (error: Error) => message.error(error.message || '删除失败'),
  });

  const columns: ColumnsType<Activity> = [
    {
      title: '活动标题',
      dataIndex: 'title',
      width: 240,
      render: (title: string, record) => (
        <Tooltip title={record.description ?? undefined}>
          <Typography.Text strong>{title}</Typography.Text>
        </Tooltip>
      ),
    },
    {
      title: '类型',
      dataIndex: 'activity_type',
      width: 90,
      render: (type: ActivityType | null) => {
        if (!type) return '—';
        const meta = TYPE_LABEL[type] ?? { text: type, color: 'default' };
        return <Tag color={meta.color}>{meta.text}</Tag>;
      },
    },
    {
      title: '活动时间',
      dataIndex: 'start_date',
      width: 220,
      render: (start: string, record) => `${start} ~ ${record.end_date}`,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      // DoD：徽章按状态着色
      render: (status: ActivityStatus) => {
        const meta = STATUS_CONFIG[status] ?? { text: status, color: 'default' };
        return <Tag color={meta.color}>{meta.text}</Tag>;
      },
    },
    {
      title: '上下架',
      dataIndex: 'is_published',
      width: 100,
      render: (published: boolean, record) => (
        <Switch
          size="small"
          checked={published}
          checkedChildren="已上架"
          unCheckedChildren="已下架"
          loading={publishMutation.isPending}
          onChange={(value) => publishMutation.mutate({ id: record.id, value })}
        />
      ),
    },
    {
      title: '排序',
      dataIndex: 'sort_weight',
      width: 80,
      render: (weight: number) => weight,
    },
    {
      title: '操作',
      key: 'actions',
      width: 130,
      fixed: 'right',
      render: (_, record) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => {
              setEditing(record);
              setModalOpen(true);
            }}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定删除该活动？"
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
        活动管理
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginTop: -8 }}>
        活动状态由起止日期实时计算；价格等详情通过「详情页链接」外部展示。
      </Typography.Paragraph>

      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          allowClear
          placeholder="全部上下架状态"
          style={{ width: 160 }}
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
            setEditing(undefined);
            setModalOpen(true);
          }}
        >
          新增活动
        </Button>
      </Space>

      <Table<Activity>
        rowKey="id"
        columns={columns}
        dataSource={listQuery.data?.items ?? []}
        loading={listQuery.isLoading}
        scroll={{ x: 1000 }}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total: listQuery.data?.total ?? 0,
          showSizeChanger: false,
          showTotal: (total) => `共 ${total} 条`,
          onChange: setPage,
        }}
      />

      <ActivityModal
        open={modalOpen}
        initial={
          editing
            ? {
                id: editing.id,
                title: editing.title,
                activity_type: editing.activity_type,
                start_date: editing.start_date,
                end_date: editing.end_date,
                description: editing.description,
                cover_image_url: editing.cover_image_url,
                detail_url: editing.detail_url,
                sort_weight: editing.sort_weight,
                is_published: editing.is_published,
              }
            : undefined
        }
        onCancel={() => setModalOpen(false)}
        onSuccess={() => {
          setModalOpen(false);
          void queryClient.invalidateQueries({ queryKey: ['activities'] });
        }}
      />
    </div>
  );
}
