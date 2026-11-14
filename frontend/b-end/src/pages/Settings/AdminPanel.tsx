/**
 * 管理员管理面板（M15-T10，API §14.1 ~ §14.5）。
 *
 * 对应原型 `settings.html` 的「管理员管理」卡片。
 *
 * **不能删除自己**（API §14.5，前端先挡住）：
 * 删掉自己会立即失去所有访问能力，且无法自行撤销。
 * 后端也会校验（25004），前端拦截只是减少误点。
 */
import { useState } from 'react';
import {
  App,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  DeleteOutlined,
  EditOutlined,
  KeyOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  createAdmin,
  deleteAdmin,
  listAdmins,
  listRoles,
  resetAdminPassword,
  updateAdmin,
  type Admin,
} from '@/services/system';
import { useAdminAuthStore } from '@/stores/auth';

const PAGE_SIZE = 10;

export function AdminPanel() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const currentAdmin = useAdminAuthStore((state) => state.admin);

  const [page, setPage] = useState(1);
  const [keyword, setKeyword] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Admin | undefined>();
  const [passwordTarget, setPasswordTarget] = useState<Admin | undefined>();

  const [form] = Form.useForm();
  const [passwordForm] = Form.useForm<{ new_password: string }>();

  const adminsQuery = useQuery({
    queryKey: ['admins', { page, keyword }],
    queryFn: () =>
      listAdmins({ keyword: keyword || undefined, page, page_size: PAGE_SIZE }),
  });

  const rolesQuery = useQuery({
    queryKey: ['roles'],
    queryFn: listRoles,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['admins'] });
    void queryClient.invalidateQueries({ queryKey: ['roles'] });
  };

  const saveMutation = useMutation({
    mutationFn: async (values: Record<string, unknown>) => {
      if (editing) {
        await updateAdmin(editing.id, {
          real_name: (values.real_name as string) || null,
          email: (values.email as string) || null,
          role_ids: values.role_ids as string[],
          status: values.status as 'active' | 'disabled',
        });
      } else {
        await createAdmin({
          username: values.username as string,
          password: values.password as string,
          real_name: (values.real_name as string) || null,
          email: (values.email as string) || null,
          role_ids: values.role_ids as string[],
        });
      }
    },
    onSuccess: () => {
      message.success(editing ? '管理员已更新' : '管理员已创建');
      setModalOpen(false);
      invalidate();
    },
    // 25002 用户名重复 / 25009 管理员不存在 等由后端返回
    onError: (error: Error) => message.error(error.message || '保存失败'),
  });

  const passwordMutation = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) =>
      resetAdminPassword(id, password),
    onSuccess: () => {
      message.success('密码已重置，该管理员需重新登录');
      setPasswordTarget(undefined);
      passwordForm.resetFields();
    },
    onError: (error: Error) => message.error(error.message || '重置失败'),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteAdmin,
    onSuccess: () => {
      message.success('管理员已删除');
      invalidate();
    },
    // 25003 仅存超管 / 25004 不能删自己
    onError: (error: Error) => message.error(error.message || '删除失败'),
  });

  const openCreate = () => {
    setEditing(undefined);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (admin: Admin) => {
    setEditing(admin);
    form.setFieldsValue({
      username: admin.username,
      real_name: admin.real_name,
      email: admin.email,
      role_ids: admin.roles.map((role) => role.id),
      status: admin.status,
    });
    setModalOpen(true);
  };

  const isSelf = (admin: Admin) => admin.id === currentAdmin?.id;

  const columns: ColumnsType<Admin> = [
    {
      title: '用户名',
      dataIndex: 'username',
      width: 140,
      render: (username: string, record) => (
        <Space size={4}>
          <Typography.Text strong>{username}</Typography.Text>
          {isSelf(record) && <Tag color="blue">当前登录</Tag>}
        </Space>
      ),
    },
    {
      title: '姓名',
      dataIndex: 'real_name',
      width: 120,
      render: (name: string | null) => name || '—',
    },
    {
      title: '角色',
      dataIndex: 'roles',
      width: 200,
      render: (_, record) => (
        <Space size={4} wrap>
          {record.roles.map((role) => (
            <Tag key={role.id} color={role.code === 'super_admin' ? 'gold' : 'default'}>
              {role.name}
            </Tag>
          ))}
        </Space>
      ),
    },
    { title: '邮箱', dataIndex: 'email', render: (email: string | null) => email || '—' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (status: string) => (
        <Tag color={status === 'active' ? 'green' : 'default'}>
          {status === 'active' ? '启用' : '禁用'}
        </Tag>
      ),
    },
    {
      title: '最后登录',
      dataIndex: 'last_login_at',
      width: 170,
      render: (time: string | null) =>
        time ? new Date(time).toLocaleString('zh-CN') : '从未登录',
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      fixed: 'right',
      render: (_, record) => (
        <Space size={2}>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEdit(record)}
          >
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            icon={<KeyOutlined />}
            onClick={() => setPasswordTarget(record)}
          >
            重置密码
          </Button>
          <Popconfirm
            title="确定删除该管理员？"
            description={
              isSelf(record) ? '不能删除自己' : '删除后该账号无法再登录'
            }
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            disabled={isSelf(record)}
            onConfirm={() => deleteMutation.mutate(record.id)}
          >
            <Button
              type="link"
              size="small"
              danger
              icon={<DeleteOutlined />}
              disabled={isSelf(record)}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const roleOptions = (rolesQuery.data?.items ?? []).map((role) => ({
    label: role.name,
    value: role.id,
  }));

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <Input.Search
          allowClear
          placeholder="搜索用户名或姓名"
          style={{ width: 240 }}
          onSearch={(value) => {
            setKeyword(value.trim());
            setPage(1);
          }}
        />
        <Button icon={<ReloadOutlined />} onClick={() => void adminsQuery.refetch()}>
          刷新
        </Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          添加管理员
        </Button>
      </Space>

      <Table<Admin>
        rowKey="id"
        columns={columns}
        dataSource={adminsQuery.data?.items ?? []}
        loading={adminsQuery.isLoading}
        scroll={{ x: 1100 }}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total: adminsQuery.data?.total ?? 0,
          showSizeChanger: false,
          showTotal: (total) => `共 ${total} 条`,
          onChange: setPage,
        }}
      />

      {/* 新增 / 编辑 */}
      <Modal
        open={modalOpen}
        title={editing ? '编辑管理员' : '添加管理员'}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={saveMutation.isPending}
        okText="保存"
        cancelText="取消"
        width={520}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          requiredMark={false}
          onFinish={(values) => saveMutation.mutate(values)}
        >
          <Form.Item
            name="username"
            label="用户名"
            extra={editing ? '用户名创建后不可修改' : '3-50 位字母、数字或下划线'}
            rules={
              editing
                ? []
                : [
                    { required: true, message: '请输入用户名' },
                    {
                      pattern: /^[A-Za-z0-9_]{3,50}$/,
                      message: '3-50 位字母、数字或下划线',
                    },
                  ]
            }
          >
            <Input placeholder="如：admin" maxLength={50} disabled={Boolean(editing)} />
          </Form.Item>

          {!editing && (
            <Form.Item
              name="password"
              label="初始密码"
              extra="8-32 位，必须包含字母与数字"
              rules={[
                { required: true, message: '请输入初始密码' },
                {
                  validator: (_, value?: string) => {
                    if (!value) return Promise.resolve();
                    if (value.length < 8 || value.length > 32) {
                      return Promise.reject(new Error('密码长度需在 8-32 位之间'));
                    }
                    if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) {
                      return Promise.reject(new Error('密码必须包含字母与数字'));
                    }
                    return Promise.resolve();
                  },
                },
              ]}
            >
              <Input.Password placeholder="至少 8 位，含字母与数字" autoComplete="new-password" />
            </Form.Item>
          )}

          <Form.Item name="real_name" label="姓名" rules={[{ max: 50, message: '最多 50 字符' }]}>
            <Input placeholder="如：张三" maxLength={50} />
          </Form.Item>

          <Form.Item name="email" label="邮箱">
            <Input placeholder="如：admin@example.com" maxLength={100} />
          </Form.Item>

          <Form.Item
            name="role_ids"
            label="角色"
            rules={[{ required: true, message: '请至少选择一个角色' }]}
          >
            <Select
              mode="multiple"
              placeholder="选择角色"
              options={roleOptions}
              loading={rolesQuery.isLoading}
            />
          </Form.Item>

          {editing && (
            <Form.Item name="status" label="状态">
              <Select
                options={[
                  { label: '启用', value: 'active' },
                  { label: '禁用', value: 'disabled' },
                ]}
              />
            </Form.Item>
          )}
        </Form>
      </Modal>

      {/* 重置密码 */}
      <Modal
        open={Boolean(passwordTarget)}
        title={`重置密码：${passwordTarget?.username ?? ''}`}
        onCancel={() => {
          setPasswordTarget(undefined);
          passwordForm.resetFields();
        }}
        onOk={() => passwordForm.submit()}
        confirmLoading={passwordMutation.isPending}
        okText="重置"
        cancelText="取消"
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary">
          重置后该管理员的所有已登录设备会立即失效，需用新密码重新登录。
        </Typography.Paragraph>
        <Form
          form={passwordForm}
          layout="vertical"
          requiredMark={false}
          onFinish={(values) => {
            if (!passwordTarget) return;
            passwordMutation.mutate({
              id: passwordTarget.id,
              password: values.new_password,
            });
          }}
        >
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              {
                validator: (_, value?: string) => {
                  if (!value) return Promise.resolve();
                  if (value.length < 8 || value.length > 32) {
                    return Promise.reject(new Error('密码长度需在 8-32 位之间'));
                  }
                  if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) {
                    return Promise.reject(new Error('密码必须包含字母与数字'));
                  }
                  return Promise.resolve();
                },
              },
            ]}
          >
            <Input.Password placeholder="至少 8 位，含字母与数字" autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
