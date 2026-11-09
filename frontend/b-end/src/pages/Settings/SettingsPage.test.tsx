/**
 * 系统设置页的组件测试（M15-T10 DoD）。
 *
 * DoD：
 *   - 站点配置表单可保存
 *   - 管理员列表可增删改
 *   - 与原型布局一致（「AI 模型」配置项已移除）
 * 边界：当前登录管理员不可删除自己。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';

import SettingsPage from './index';
import type { PageData } from '@/types/api';
import type {
  Admin,
  PermissionGroup,
  Role,
  SiteSettings,
} from '@/services/system';
import { useAdminAuthStore } from '@/stores/auth';

const mockGetSettings = vi.fn();
const mockUpdateSettings = vi.fn();
const mockListAdmins = vi.fn();
const mockCreateAdmin = vi.fn();
const mockUpdateAdmin = vi.fn();
const mockDeleteAdmin = vi.fn();
const mockResetPassword = vi.fn();
const mockListRoles = vi.fn();
const mockListPermissions = vi.fn();
const mockGetRole = vi.fn();
const mockCreateRole = vi.fn();
const mockUpdateRole = vi.fn();
const mockSetRolePermissions = vi.fn();
const mockDeleteRole = vi.fn();

vi.mock('@/services/system', async () => {
  const actual = await vi.importActual<typeof import('@/services/system')>(
    '@/services/system',
  );
  return {
    ...actual,
    getSiteSettings: (...a: unknown[]) => mockGetSettings(...a),
    updateSiteSettings: (...a: unknown[]) => mockUpdateSettings(...a),
    listAdmins: (...a: unknown[]) => mockListAdmins(...a),
    createAdmin: (...a: unknown[]) => mockCreateAdmin(...a),
    updateAdmin: (...a: unknown[]) => mockUpdateAdmin(...a),
    deleteAdmin: (...a: unknown[]) => mockDeleteAdmin(...a),
    resetAdminPassword: (...a: unknown[]) => mockResetPassword(...a),
    listRoles: (...a: unknown[]) => mockListRoles(...a),
    listPermissions: (...a: unknown[]) => mockListPermissions(...a),
    getRole: (...a: unknown[]) => mockGetRole(...a),
    createRole: (...a: unknown[]) => mockCreateRole(...a),
    updateRole: (...a: unknown[]) => mockUpdateRole(...a),
    setRolePermissions: (...a: unknown[]) => mockSetRolePermissions(...a),
    deleteRole: (...a: unknown[]) => mockDeleteRole(...a),
  };
});

const SETTINGS: SiteSettings = {
  site_name: '云游坊',
  site_description: '智能旅游规划平台',
  allow_registration: true,
  allow_content_review: true,
};

const SELF_ADMIN: Admin = {
  id: 'admin-self',
  username: 'admin',
  real_name: '超级管理员',
  email: 'admin@example.com',
  status: 'active',
  roles: [{ id: 'role-super', code: 'super_admin', name: '超级管理员' }],
  last_login_at: '2026-11-08T10:00:00Z',
  created_at: '2026-01-01T00:00:00Z',
};

const OTHER_ADMIN: Admin = {
  id: 'admin-other',
  username: 'editor',
  real_name: '内容编辑',
  email: 'editor@example.com',
  status: 'active',
  roles: [{ id: 'role-normal', code: 'normal', name: '普通管理员' }],
  last_login_at: null,
  created_at: '2026-01-02T00:00:00Z',
};

const ROLES: Role[] = [
  {
    id: 'role-super',
    code: 'super_admin',
    name: '超级管理员',
    description: '拥有全部权限',
    is_builtin: true,
    admin_count: 1,
    permission_count: 76,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'role-normal',
    code: 'normal',
    name: '普通管理员',
    description: null,
    is_builtin: true,
    admin_count: 1,
    permission_count: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'role-custom',
    code: 'content_editor',
    name: '内容编辑',
    description: '只能管内容',
    is_builtin: false,
    admin_count: 0,
    permission_count: 2,
    created_at: '2026-01-03T00:00:00Z',
    updated_at: '2026-01-03T00:00:00Z',
  },
];

const PERMISSION_GROUPS: PermissionGroup[] = [
  {
    module: 'catalog',
    permissions: [
      {
        id: 'p1',
        code: 'catalog.attraction.read',
        module: 'catalog',
        action: 'read',
        name: '查看景点',
        description: null,
      },
      {
        id: 'p2',
        code: 'catalog.attraction.create',
        module: 'catalog',
        action: 'create',
        name: '创建景点',
        description: null,
      },
    ],
  },
  {
    module: 'system',
    permissions: [
      {
        id: 'p3',
        code: 'system.admin.read',
        module: 'system',
        action: 'read',
        name: '查看管理员',
        description: null,
      },
    ],
  },
];

function makePage(items: Admin[]): PageData<Admin> {
  return { items, total: items.length, page: 1, page_size: 10, total_pages: 1 };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={zhCN}>
        <AntdApp>
          <SettingsPage />
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>,
  );
}

describe('SettingsPage', () => {
  beforeEach(() => {
    mockGetSettings.mockReset().mockResolvedValue(SETTINGS);
    mockUpdateSettings.mockReset().mockResolvedValue(undefined);
    mockListAdmins.mockReset().mockResolvedValue(makePage([SELF_ADMIN, OTHER_ADMIN]));
    mockListRoles.mockReset().mockResolvedValue({ items: ROLES });
    mockListPermissions.mockReset().mockResolvedValue({
      items: PERMISSION_GROUPS.flatMap((g) => g.permissions),
      groups: PERMISSION_GROUPS,
      total: 3,
    });

    useAdminAuthStore.setState({
      accessToken: 'token',
      admin: {
        id: SELF_ADMIN.id,
        username: SELF_ADMIN.username,
        real_name: SELF_ADMIN.real_name,
        roles: [{ id: 'role-super', code: 'super_admin', name: '超级管理员' }],
      },
    });
  });

  describe('三个页签（与原型布局一致）', () => {
    it('渲染基础设置、管理员管理、角色权限三个页签', () => {
      renderPage();

      expect(screen.getByRole('tab', { name: '基础设置' })).toBeInTheDocument();
      expect(screen.getByRole('tab', { name: '管理员管理' })).toBeInTheDocument();
      expect(screen.getByRole('tab', { name: '角色权限' })).toBeInTheDocument();
    });

    it('**不渲染 AI 模型配置**（已由 M12 承担）', () => {
      renderPage();

      expect(screen.queryByText('AI 对话设置')).not.toBeInTheDocument();
      expect(screen.queryByText('AI模型')).not.toBeInTheDocument();
    });

    it('页面提示 AI 模型配置已移至模型管理', () => {
      renderPage();

      // antd 会把长文案拆成多个文本节点，直接在 body 文本里找
      expect(document.body.textContent).toContain(
        'AI 模型配置已移至「模型管理」',
      );
    });
  });

  describe('基础设置（DoD：表单可保存）', () => {
    it('回显当前配置', async () => {
      renderPage();

      await waitFor(() => {
        expect(screen.getByDisplayValue('云游坊')).toBeInTheDocument();
      });
      expect(screen.getByDisplayValue('智能旅游规划平台')).toBeInTheDocument();
    });

    it('修改后保存调用更新接口', async () => {
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByDisplayValue('云游坊')).toBeInTheDocument();
      });

      const nameInput = screen.getByDisplayValue('云游坊');
      await user.clear(nameInput);
      await user.type(nameInput, '新站名');

      await user.click(screen.getByRole('button', { name: /保\s*存/ }));

      await waitFor(
        () => {
          expect(mockUpdateSettings).toHaveBeenCalled();
        },
        { timeout: 3000 },
      );

      const payload = mockUpdateSettings.mock.calls[0]?.[0] as Record<string, unknown>;
      expect(payload.site_name).toBe('新站名');
    });

    it('保存成功后提示', async () => {
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByDisplayValue('云游坊')).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /保\s*存/ }));

      await waitFor(() => {
        expect(screen.getByText('配置已保存')).toBeInTheDocument();
      });
    });

    it('网站名称为空时阻止提交', async () => {
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByDisplayValue('云游坊')).toBeInTheDocument();
      });

      await user.clear(screen.getByDisplayValue('云游坊'));
      await user.click(screen.getByRole('button', { name: /保\s*存/ }));

      await waitFor(() => {
        expect(screen.getByText('请输入网站名称')).toBeInTheDocument();
      });
      expect(mockUpdateSettings).not.toHaveBeenCalled();
    });
  });

  describe('管理员管理（DoD：可增删改）', () => {
    async function openAdminTab() {
      const user = userEvent.setup();
      renderPage();
      await user.click(screen.getByRole('tab', { name: '管理员管理' }));
      return user;
    }

    it('列出管理员并标记当前登录', async () => {
      await openAdminTab();

      await waitFor(() => {
        expect(screen.getByText('admin')).toBeInTheDocument();
      });
      expect(screen.getByText('editor')).toBeInTheDocument();
      expect(screen.getByText('当前登录')).toBeInTheDocument();
    });

    it('显示角色与状态', async () => {
      await openAdminTab();

      await waitFor(() => {
        expect(screen.getByText('admin')).toBeInTheDocument();
      });
      expect(screen.getAllByText('超级管理员').length).toBeGreaterThan(0);
      expect(screen.getAllByText('启用').length).toBeGreaterThan(0);
    });

    it('从未登录的管理员显示占位', async () => {
      await openAdminTab();

      await waitFor(() => {
        expect(screen.getByText('从未登录')).toBeInTheDocument();
      });
    });

    it('「添加管理员」打开表单', async () => {
      const user = await openAdminTab();

      await waitFor(() => {
        expect(screen.getByText('admin')).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /添加管理员/ }));

      await waitFor(() => {
        expect(screen.getByText('添加管理员', { selector: '.ant-modal-title' })).toBeInTheDocument();
      });
      expect(screen.getByText('初始密码')).toBeInTheDocument();
    });

    it('编辑时不显示密码字段', async () => {
      const user = await openAdminTab();

      await waitFor(() => {
        expect(screen.getByText('editor')).toBeInTheDocument();
      });

      const otherRow = screen.getByText('editor').closest('tr');
      expect(otherRow).not.toBeNull();

      await user.click(
        within(otherRow as HTMLElement).getByText('编辑').closest('button')!,
      );

      await waitFor(() => {
        expect(screen.getByText('编辑管理员')).toBeInTheDocument();
      });
      expect(screen.queryByText('初始密码')).not.toBeInTheDocument();
    });

    it('**当前登录管理员删除按钮禁用**（边界）', async () => {
      await openAdminTab();

      await waitFor(() => {
        expect(screen.getByText('admin')).toBeInTheDocument();
      });

      const selfRow = screen.getByText('admin').closest('tr');
      const deleteButton = within(selfRow as HTMLElement)
        .getByText('删除')
        .closest('button');

      expect(deleteButton).toBeDisabled();
    });

    it('其他管理员删除按钮可用', async () => {
      await openAdminTab();

      await waitFor(() => {
        expect(screen.getByText('editor')).toBeInTheDocument();
      });

      const otherRow = screen.getByText('editor').closest('tr');
      const deleteButton = within(otherRow as HTMLElement)
        .getByText('删除')
        .closest('button');

      expect(deleteButton).not.toBeDisabled();
    });

    it('重置密码弹窗说明会使其他设备失效', async () => {
      const user = await openAdminTab();

      await waitFor(() => {
        expect(screen.getByText('editor')).toBeInTheDocument();
      });

      const otherRow = screen.getByText('editor').closest('tr');
      await user.click(
        within(otherRow as HTMLElement)
          .getByText('重置密码')
          .closest('button')!,
      );

      await waitFor(() => {
        expect(
          screen.getByText(/重置后该管理员的所有已登录设备会立即失效/),
        ).toBeInTheDocument();
      });
    });
  });

  describe('角色权限', () => {
    async function openRoleTab() {
      const user = userEvent.setup();
      renderPage();
      await user.click(screen.getByRole('tab', { name: '角色权限' }));
      return user;
    }

    it('列出角色并标记内置', async () => {
      await openRoleTab();

      await waitFor(() => {
        expect(screen.getByText('super_admin')).toBeInTheDocument();
      });
      expect(screen.getByText('content_editor')).toBeInTheDocument();
      expect(screen.getAllByText('内置').length).toBe(2);
    });

    it('显示管理员数与权限项数', async () => {
      await openRoleTab();

      await waitFor(() => {
        expect(screen.getByText('super_admin')).toBeInTheDocument();
      });
      // 超级管理员有 76 个权限项
      expect(screen.getByText('76')).toBeInTheDocument();
    });

    it('**内置角色删除按钮禁用**', async () => {
      await openRoleTab();

      await waitFor(() => {
        expect(screen.getByText('super_admin')).toBeInTheDocument();
      });

      const row = screen.getByText('super_admin').closest('tr');
      const deleteButton = within(row as HTMLElement)
        .getByText('删除')
        .closest('button');

      expect(deleteButton).toBeDisabled();
    });

    it('自定义角色删除按钮可用', async () => {
      await openRoleTab();

      await waitFor(() => {
        expect(screen.getByText('content_editor')).toBeInTheDocument();
      });

      const row = screen.getByText('content_editor').closest('tr');
      const deleteButton = within(row as HTMLElement)
        .getByText('删除')
        .closest('button');

      expect(deleteButton).not.toBeDisabled();
    });

    it('「配置权限」打开按模块分组的勾选树', async () => {
      const user = await openRoleTab();

      await waitFor(() => {
        expect(screen.getByText('content_editor')).toBeInTheDocument();
      });

      const row = screen.getByText('content_editor').closest('tr');
      await user.click(
        within(row as HTMLElement).getByText('配置权限').closest('button')!,
      );

      await waitFor(() => {
        expect(screen.getByText('基础数据')).toBeInTheDocument();
      });
      // 模块分组标题
      expect(screen.getByText('系统管理')).toBeInTheDocument();
      // 权限项
      expect(screen.getByText('查看景点')).toBeInTheDocument();
    });

    it('新建角色时编码字段可编辑', async () => {
      const user = await openRoleTab();

      await waitFor(() => {
        expect(screen.getByText('content_editor')).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /新建角色/ }));

      await waitFor(() => {
        expect(
          screen.getByText('新建角色', { selector: '.ant-modal-title' }),
        ).toBeInTheDocument();
      });

      const codeInput = screen.getByPlaceholderText('如：content_editor');
      expect(codeInput).not.toBeDisabled();
    });
  });
});
