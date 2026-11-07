/**
 * B 端整体布局：侧边栏 + 顶部栏。
 *
 * 菜单与需求文档的 B 端功能一一对应，新增页面在此登记。
 */
import { Layout, Menu, Avatar, Dropdown, Space, Typography } from 'antd';
import {
  AppstoreOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  EnvironmentOutlined,
  HomeOutlined,
  LogoutOutlined,
  SettingOutlined,
  ShopOutlined,
  TeamOutlined,
  UserOutlined,
  ApartmentOutlined,
} from '@ant-design/icons';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';

import { useAdminAuthStore } from '@/stores/auth';

const { Header, Sider, Content } = Layout;

const MENU_ITEMS = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '数据看板' },
  { key: '/attractions', icon: <EnvironmentOutlined />, label: '景点管理' },
  { key: '/restaurants', icon: <ShopOutlined />, label: '餐厅管理' },
  { key: '/hotels', icon: <HomeOutlined />, label: '酒店管理' },
  { key: '/knowledge-base', icon: <DatabaseOutlined />, label: 'RAG 知识库' },
  { key: '/knowledge-graph', icon: <ApartmentOutlined />, label: '知识图谱' },
  { key: '/models', icon: <AppstoreOutlined />, label: '模型管理' },
  { key: '/users', icon: <TeamOutlined />, label: '用户管理' },
  { key: '/settings', icon: <SettingOutlined />, label: '系统设置' },
];

export function AdminLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { admin, clear } = useAdminAuthStore();

  const selectedKey =
    MENU_ITEMS.find((item) => location.pathname.startsWith(item.key))?.key ?? '/dashboard';

  const handleLogout = () => {
    clear();
    navigate('/login', { replace: true });
  };

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={220} theme="dark" breakpoint="lg" collapsedWidth={64}>
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontSize: 17,
            fontWeight: 600,
          }}
        >
          云游坊后台
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={MENU_ITEMS}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>

      <Layout>
        <Header
          style={{
            background: '#fff',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <Dropdown
            menu={{
              items: [{ key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: handleLogout }],
            }}
          >
            <Space style={{ cursor: 'pointer' }}>
              <Avatar icon={<UserOutlined />} size="small" />
              <Typography.Text>{admin?.display_name ?? admin?.username ?? '管理员'}</Typography.Text>
            </Space>
          </Dropdown>
        </Header>

        <Content style={{ margin: 24, background: '#fff', borderRadius: 8, padding: 24 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
