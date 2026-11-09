/**
 * 角色与权限管理面板（M15-T10，API §14.6 ~ §14.10）。
 *
 * 权限勾选树按 `module` 分组（后端 `groups` 已分好），
 * 提交时拍平成 `permission_ids` 数组——整体替换语义。
 *
 * **内置角色不可删除**（API §14.8，前端先置灰）：
 * 它们被代码直接引用，删掉会让「谁有全部权限」失去依据。
 */
import { useEffect, useState } from 'react';
import {
  App,
  Button,
  Checkbox,
  Divider,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  createRole,
  deleteRole,
  getRole,
  listPermissions,
  listRoles,
  setRolePermissions,
  updateRole,
  type Role,
} from '@/services/system';

/** 模块编码 → 中文名（权限勾选树的分组标题） */
const MODULE_LABELS: Record<string, string> = {
  catalog: '基础数据',
  knowledge_base: '知识库',
  knowledge_graph: '知识图谱',
  model: '模型管理',
  quota: '额度服务',
  user_ops: '用户运营',
  system: '系统管理',
  dashboard: '数据看板',
};

const ACTION_LABELS: Record<string, string> = {
  create: '创建',
  read: '查看',
  update: '编辑',
  delete: '删除',
  export: '导出',
  manage: '管理',
};

export function RolePanel() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [modalOpen, setModalOpen] = useState(false);
  const [permissionModalOpen, setPermissionModalOpen] = useState(false);
  const [editing, setEditing] = useState<Role | undefined>();
  const [permissionTarget, setPermissionTarget] = useState<Role | undefined>();
  const [selectedPermissionIds, setSelectedPermissionIds] = useState<string[]>([]);

  const [form] = Form.useForm<{ code: string; name: string; description?: string }>();

  const rolesQuery = useQuery({ queryKey: ['roles'], queryFn: listRoles });
  const permissionsQuery = useQuery({
    queryKey: ['permissions'],
    queryFn: listPermissions,
    staleTime: 10 * 60 * 1000,
  });

  const roleDetailQuery = useQuery({
    queryKey: ['role-detail', permissionTarget?.id],
    queryFn: () => getRole(permissionTarget!.id),
    enabled: Boolean(permissionTarget),
  });

  // 打开权限弹窗时，用已有的权限项初始化勾选状态
  useEffect(() => {
    if (roleDetailQuery.data) {
      setSelectedPermissionIds(
        roleDetailQuery.data.permissions.map((item) => item.id),
      );
    }
  }, [roleDetailQuery.data]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['roles'] });
    void queryClient.invalidateQueries({ queryKey: ['role-detail'] });
  };

  const saveMutation = useMutation({
    mutationFn: async (values: { code: string; name: string; description?: string }) => {
      if (editing) {
        await updateRole(editing.id, {
          name: values.name,
          description: values.description ?? null,
        });
      } else {
        await createRole({
          code: values.code,
          name: values.name,
          description: values.description ?? null,
        });
      }
    },
    onSuccess: () => {
      message.success(editing ? '角色已更新' : '角色已创建');
      setModalOpen(false);
      invalidate();
    },
    // 25014 编码重复
    onError: (error: Error) => message.error(error.message || '保存失败'),
  });

  const permissionMutation = useMutation({
    mutationFn: ({ id, ids }: { id: string; ids: string[] }) =>
      setRolePermissions(id, ids),
    onSuccess: () => {
      message.success('权限已更新');
      setPermissionModalOpen(false);
      invalidate();
    },
    onError: (error: Error) => message.error(error.message || '保存失败'),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteRole,
    onSuccess: () => {
      message.success('角色已删除');
      invalidate();
    },
    // 25005 已分配 / 25006 内置角色
    onError: (error: Error) => message.error(error.message || '删除失败'),
  });

  const openCreate = () => {
    setEditing(undefined);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (role: Role) => {
    setEditing(role);
    form.setFieldsValue({
      code: role.code,
      name: role.name,
      description: role.description ?? undefined,
    });
    setModalOpen(true);
  };

  const openPermissions = (role: Role) => {
    setPermissionTarget(role);
    setSelectedPermissionIds([]);
    setPermissionModalOpen(true);
  };

  const columns: ColumnsType<Role> = [
    {
      title: '角色编码',
      dataIndex: 'code',
      width: 160,
      render: (code: string) => <Typography.Text code>{code}</Typography.Text>,
    },
    {
      title: '角色名称',
      dataIndex: 'name',
      width: 160,
      render: (name: string, record) => (
        <Space size={4}>
          <Typography.Text strong>{name}</Typography.Text>
          {record.is_builtin && <Tag color="gold">内置</Tag>}
        </Space>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      render: (desc: string | null) => desc || '—',
    },
    {
      title: '管理员数',
      dataIndex: 'admin_count',
      width: 100,
      render: (count: number) => <Tag color={count > 0 ? 'blue' : 'default'}>{count}</Tag>,
    },
    {
      title: '权限项',
      dataIndex: 'permission_count',
      width: 100,
      render: (count: number) => <Tag color={count > 0 ? 'green' : 'default'}>{count}</Tag>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 230,
      fixed: 'right',
      render: (_, record) => (
        <Space size={2}>
          <Button type="link" size="small" onClick={() => openPermissions(record)}>
            配置权限
          </Button>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEdit(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定删除该角色？"
            description={
              record.is_builtin
                ? '内置角色不可删除'
                : record.admin_count > 0
                  ? `该角色已分配给 ${record.admin_count} 个管理员，删除会被拒绝`
                  : undefined
            }
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            disabled={record.is_builtin}
            onConfirm={() => deleteMutation.mutate(record.id)}
          >
            <Button
              type="link"
              size="small"
              danger
              icon={<DeleteOutlined />}
              disabled={record.is_builtin}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  /** 全选/取消全选某个模块 */
  const toggleModule = (modulePermissions: { id: string }[], checked: boolean) => {
    const ids = modulePermissions.map((item) => item.id);
    setSelectedPermissionIds((prev) =>
      checked
        ? Array.from(new Set([...prev, ...ids]))
        : prev.filter((id) => !ids.includes(id)),
    );
  };

  const groups = permissionsQuery.data?.groups ?? [];

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <Button icon={<ReloadOutlined />} onClick={() => void rolesQuery.refetch()}>
          刷新
        </Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建角色
        </Button>
      </Space>

      <Table<Role>
        rowKey="id"
        columns={columns}
        dataSource={rolesQuery.data?.items ?? []}
        loading={rolesQuery.isLoading}
        scroll={{ x: 1000 }}
        pagination={false}
      />

      {/* 新建 / 编辑角色 */}
      <Modal
        open={modalOpen}
        title={editing ? '编辑角色' : '新建角色'}
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
            name="code"
            label="角色编码"
            extra={editing ? '编码创建后不可修改' : '小写字母开头，可含数字与下划线'}
            rules={
              editing
                ? []
                : [
                    { required: true, message: '请输入角色编码' },
                    {
                      pattern: /^[a-z][a-z0-9_]{1,49}$/,
                      message: '小写字母开头，2-50 位',
                    },
                  ]
            }
          >
            <Input placeholder="如：content_editor" maxLength={50} disabled={Boolean(editing)} />
          </Form.Item>

          <Form.Item
            name="name"
            label="角色名称"
            rules={[
              { required: true, message: '请输入角色名称' },
              { max: 50, message: '最多 50 字符' },
            ]}
          >
            <Input placeholder="如：内容编辑" maxLength={50} />
          </Form.Item>

          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={200} showCount />
          </Form.Item>
        </Form>
      </Modal>

      {/* 配置权限 */}
      <Modal
        open={permissionModalOpen}
        title={`配置权限：${permissionTarget?.name ?? ''}`}
        onCancel={() => setPermissionModalOpen(false)}
        onOk={() => {
          if (!permissionTarget) return;
          permissionMutation.mutate({
            id: permissionTarget.id,
            ids: selectedPermissionIds,
          });
        }}
        confirmLoading={permissionMutation.isPending}
        okText="保存"
        cancelText="取消"
        width={720}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary">
          勾选该角色拥有的权限项。提交后整体替换原有配置。
        </Typography.Paragraph>

        {groups.length === 0 ? (
          <Empty description="暂无权限项" />
        ) : (
          <div style={{ maxHeight: 480, overflowY: 'auto' }}>
            {groups.map((group, index) => {
              const allChecked = group.permissions.every((item) =>
                selectedPermissionIds.includes(item.id),
              );
              const someChecked =
                !allChecked &&
                group.permissions.some((item) =>
                  selectedPermissionIds.includes(item.id),
                );

              return (
                <div key={group.module}>
                  {index > 0 && <Divider style={{ margin: '12px 0' }} />}
                  <div style={{ marginBottom: 8 }}>
                    <Checkbox
                      checked={allChecked}
                      indeterminate={someChecked}
                      onChange={(event) =>
                        toggleModule(group.permissions, event.target.checked)
                      }
                    >
                      <Typography.Text strong>
                        {MODULE_LABELS[group.module] ?? group.module}
                      </Typography.Text>
                    </Checkbox>
                  </div>

                  <Checkbox.Group
                    value={selectedPermissionIds}
                    onChange={(values) =>
                      setSelectedPermissionIds(values as string[])
                    }
                    style={{ paddingLeft: 24, display: 'flex', flexWrap: 'wrap', gap: 8 }}
                  >
                    {group.permissions.map((permission) => (
                      <Checkbox key={permission.id} value={permission.id}>
                        {permission.name}
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          （{ACTION_LABELS[permission.action] ?? permission.action}）
                        </Typography.Text>
                      </Checkbox>
                    ))}
                  </Checkbox.Group>
                </div>
              );
            })}
          </div>
        )}
      </Modal>
    </div>
  );
}
