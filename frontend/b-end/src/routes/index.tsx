/**
 * 路由表。
 *
 * 页面按需求文档 B 端功能一一对应，业务页面在后续任务中补充，
 * 当前先建立路由骨架与占位页，保证导航可用。
 */
import { Navigate, Route, Routes } from 'react-router-dom';

import { AdminLayout } from '@/components/layout/AdminLayout';
import { RequireAdmin } from '@/components/layout/RequireAdmin';
import ActivitiesPage from '@/pages/Activities';
import AttractionsPage from '@/pages/Attractions';
import CategoriesPage from '@/pages/Categories';
import HotelsPage from '@/pages/Hotels';
import ModelsPage from '@/pages/Models';
import RegionsPage from '@/pages/Regions';
import { LoginPage } from '@/pages/Login';
import RestaurantsPage from '@/pages/Restaurants';
import SettingsPage from '@/pages/Settings';
import { PlaceholderPage } from '@/pages/Placeholder';

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      {/* 受保护区域：未登录跳转 /login（仅导航控制，鉴权由后端负责） */}
      <Route element={<RequireAdmin />}>
        <Route element={<AdminLayout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<PlaceholderPage title="数据看板" />} />
          <Route path="/regions" element={<RegionsPage />} />
          <Route path="/categories" element={<CategoriesPage />} />
          <Route path="/attractions" element={<AttractionsPage />} />
          <Route path="/restaurants" element={<RestaurantsPage />} />
          <Route path="/hotels" element={<HotelsPage />} />
          <Route path="/activities" element={<ActivitiesPage />} />
          <Route path="/knowledge-base" element={<PlaceholderPage title="RAG 知识库" />} />
          <Route path="/knowledge-graph" element={<PlaceholderPage title="知识图谱" />} />
          <Route path="/models" element={<ModelsPage />} />
          <Route path="/users" element={<PlaceholderPage title="用户管理" />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
