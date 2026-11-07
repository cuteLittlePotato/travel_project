/**
 * 路由表。
 *
 * 页面按需求文档 B 端功能一一对应，业务页面在后续任务中补充，
 * 当前先建立路由骨架与占位页，保证导航可用。
 */
import { Navigate, Route, Routes } from 'react-router-dom';

import { AdminLayout } from '@/components/layout/AdminLayout';
import { RequireAdmin } from '@/components/layout/RequireAdmin';
import { LoginPage } from '@/pages/Login';
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
          <Route path="/attractions" element={<PlaceholderPage title="景点管理" />} />
          <Route path="/restaurants" element={<PlaceholderPage title="餐厅管理" />} />
          <Route path="/hotels" element={<PlaceholderPage title="酒店管理" />} />
          <Route path="/knowledge-base" element={<PlaceholderPage title="RAG 知识库" />} />
          <Route path="/knowledge-graph" element={<PlaceholderPage title="知识图谱" />} />
          <Route path="/models" element={<PlaceholderPage title="模型管理" />} />
          <Route path="/users" element={<PlaceholderPage title="用户管理" />} />
          <Route path="/settings" element={<PlaceholderPage title="系统设置" />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
