/**
 * B 端省市管理页（M11-T14，API §12.1 ~ §12.8）。
 *
 * 层级展示：省份为主表，展开省份行显示其下城市（`province_id` 过滤）。
 * 城市按需加载——省份可能上百个，一次性拉全部城市不划算。
 */
import { useState } from 'react';
import {
  App,
  Button,
  Input,
  Popconfirm,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { RegionModal, type RegionModalMode } from './RegionModal';
import {
  deleteCity,
  deleteProvince,
  listCities,
  listProvinces,
  type CityListItem,
  type ProvinceListItem,
} from '@/services/catalog';

const CITY_PAGE_SIZE = 10;

/** 城市子表：展开省份行时按需拉取（DoD：省份展开显示城市） */
function CitySubTable({
  province,
  onEdit,
}: {
  province: ProvinceListItem;
  onEdit: (city: CityListItem) => void;
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);

  const citiesQuery = useQuery({
    queryKey: ['cities', province.id, page],
    queryFn: () =>
      listCities({ province_id: province.id, page, page_size: CITY_PAGE_SIZE }),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteCity,
    onSuccess: () => {
      message.success('城市已删除');
      void queryClient.invalidateQueries({ queryKey: ['cities', province.id] });
      void queryClient.invalidateQueries({ queryKey: ['provinces'] });
    },
    // 有景点/餐厅/酒店引用时后端返回 21003（HTTP 409）
    onError: (error: Error) => message.error(error.message || '删除失败'),
  });

  const columns: ColumnsType<CityListItem> = [
    { title: '城市名称', dataIndex: 'name', width: 200 },
    { title: '行政区划编码', dataIndex: 'code', width: 140 },
    {
      title: '热度',
      dataIndex: 'heat_score',
      width: 100,
      render: (score: string) => Number(score).toFixed(1),
    },
    {
      title: '景点数',
      dataIndex: 'attraction_count',
      width: 100,
      render: (count: number) => (
        <Tag color={count > 0 ? 'blue' : 'default'}>{count}</Tag>
      ),
    },
    {
      title: '排序',
      dataIndex: 'sort_weight',
      width: 80,
    },
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
            title="确定删除该城市？"
            description={
              record.attraction_count > 0
                ? `该城市下还有 ${record.attraction_count} 个景点，删除会被拒绝`
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
    <Table<CityListItem>
      rowKey="id"
      size="small"
      columns={columns}
      dataSource={citiesQuery.data?.items ?? []}
      loading={citiesQuery.isLoading}
      pagination={{
        current: page,
        pageSize: CITY_PAGE_SIZE,
        total: citiesQuery.data?.total ?? 0,
        showSizeChanger: false,
        size: 'small',
        onChange: setPage,
      }}
    />
  );
}

export default function RegionsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [keyword, setKeyword] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [mode, setMode] = useState<RegionModalMode>('province');
  const [editing, setEditing] = useState<ProvinceListItem | CityListItem | undefined>();
  const [parentProvince, setParentProvince] = useState<ProvinceListItem | undefined>();

  const provincesQuery = useQuery({
    queryKey: ['provinces', keyword],
    queryFn: () => listProvinces(keyword || undefined),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteProvince,
    onSuccess: () => {
      message.success('省份已删除');
      void queryClient.invalidateQueries({ queryKey: ['provinces'] });
    },
    // 有下级城市时后端返回 21002（HTTP 409）
    onError: (error: Error) => message.error(error.message || '删除失败'),
  });

  const openProvinceModal = (record?: ProvinceListItem) => {
    setMode('province');
    setEditing(record);
    setParentProvince(undefined);
    setModalOpen(true);
  };

  const openCityModal = (province: ProvinceListItem, city?: CityListItem) => {
    setMode('city');
    setEditing(city);
    setParentProvince(province);
    setModalOpen(true);
  };

  const provinceColumns: ColumnsType<ProvinceListItem> = [
    {
      title: '省份名称',
      dataIndex: 'name',
      width: 200,
      render: (name: string) => <Typography.Text strong>{name}</Typography.Text>,
    },
    { title: '行政区划编码', dataIndex: 'code', width: 140 },
    {
      title: '热度',
      dataIndex: 'heat_score',
      width: 100,
      render: (score: string) => Number(score).toFixed(1),
    },
    {
      title: '城市数',
      dataIndex: 'city_count',
      width: 100,
      render: (count: number) => <Tag color={count > 0 ? 'blue' : 'default'}>{count}</Tag>,
    },
    { title: '排序', dataIndex: 'sort_weight', width: 80 },
    {
      title: '操作',
      key: 'actions',
      width: 210,
      render: (_, record) => (
        <Space size={4}>
          <Tooltip title="在该省份下新增城市">
            <Button
              type="link"
              size="small"
              icon={<PlusOutlined />}
              onClick={() => openCityModal(record)}
            >
              加城市
            </Button>
          </Tooltip>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openProvinceModal(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定删除该省份？"
            description={
              record.city_count > 0
                ? `该省份下还有 ${record.city_count} 个城市，删除会被拒绝`
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
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        省市管理
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginTop: -8 }}>
        省份为主表，展开行查看城市。删除省份前需先清空其下城市；删除城市前需先解除景点、餐厅、酒店的引用。
      </Typography.Paragraph>

      <Space style={{ marginBottom: 16 }} wrap>
        <Input.Search
          allowClear
          placeholder="搜索省份名称"
          style={{ width: 240 }}
          onSearch={(value) => setKeyword(value.trim())}
        />
        <Button icon={<ReloadOutlined />} onClick={() => void provincesQuery.refetch()}>
          刷新
        </Button>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => openProvinceModal()}
        >
          新增省份
        </Button>
      </Space>

      <Table<ProvinceListItem>
        rowKey="id"
        columns={provinceColumns}
        dataSource={provincesQuery.data?.items ?? []}
        loading={provincesQuery.isLoading}
        expandable={{
          expandedRowRender: (record) => (
            <CitySubTable province={record} onEdit={(city) => openCityModal(record, city)} />
          ),
        }}
        pagination={false}
      />

      <RegionModal
        open={modalOpen}
        mode={mode}
        parentProvince={parentProvince}
        initial={editing}
        onCancel={() => setModalOpen(false)}
        onSuccess={() => {
          setModalOpen(false);
          void queryClient.invalidateQueries({ queryKey: ['provinces'] });
          if (parentProvince) {
            void queryClient.invalidateQueries({
              queryKey: ['cities', parentProvince.id],
            });
          }
        }}
      />
    </div>
  );
}
