/**
 * B 端整体布局：侧边栏 + 顶部栏。
 *
 * 菜单与需求文档的 B 端功能一一对应，新增页面在此登记。
 */
import { Layout, Menu, Avatar, Breadcrumb, Dropdown, Space, Typography } from 'antd';
import {
  ApartmentOutlined,
  AppstoreAddOutlined,
  AppstoreOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  EnvironmentOutlined,
  GlobalOutlined,
  HomeOutlined,
  LogoutOutlined,
  SettingOutlined,
  ShopOutlined,
  TagOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';

import { logout } from '@/services/auth';
import { useAdminAuthStore } from '@/stores/auth';

const { Header, Sider, Content } = Layout;

const MENU_ITEMS = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '数据看板' },
  { key: '/regions', icon: <GlobalOutlined />, label: '省市管理' },
  { key: '/categories', icon: <AppstoreAddOutlined />, label: '分类管理' },
  { key: '/attractions', icon: <EnvironmentOutlined />, label: '景点管理' },
  { key: '/restaurants', icon: <ShopOutlined />, label: '餐厅管理' },
  { key: '/hotels', icon: <HomeOutlined />, label: '酒店管理' },
  { key: '/activities', icon: <TagOutlined />, label: '活动管理' },
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

  const currentItem = MENU_ITEMS.find((item) => location.pathname.startsWith(item.key));
  const selectedKey = currentItem?.key ?? '/dashboard';

  // 面包屑：首页 > 当前菜单
  const breadcrumbItems = [
    { title: '首页' },
    ...(currentItem ? [{ title: currentItem.label }] : []),
  ];

  const handleLogout = async () => {
    // 先调后端登出（全端登出，token_version 自增），
    // 即使请求失败也要清本地状态——否则用户卡在「点了没反应」
    try {
      await logout();
    } catch {
      // 网络异常时仍然允许本地登出
    } finally {
      clear();
      navigate('/login', { replace: true });
    }
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
              <Typography.Text>{admin?.real_name ?? admin?.username ?? '管理员'}</Typography.Text>
            </Space>
          </Dropdown>
        </Header>

        <Content style={{ margin: 24 }}>
          <Breadcrumb items={breadcrumbItems} style={{ marginBottom: 16 }} />
          <div style={{ background: '#fff', borderRadius: 8, padding: 24 }}>
            <Outlet />
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}
