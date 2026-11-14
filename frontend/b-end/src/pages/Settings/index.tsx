/**
 * B 端系统设置页（M15-T10，原型 `prototype/b-end/settings.html`）。
 *
 * 三个页签对应原型的三个卡片区块：
 *   - 基础设置：站点配置（API §14.12 / §14.13）
 *   - 管理员管理：管理员 CRUD（API §14.1 ~ §14.5）
 *   - 角色权限：角色 CRUD 与权限分配（API §14.6 ~ §14.10）
 *
 * **原型的「AI 对话设置」卡片已移除**——AI 模型由 M12 模型管理承担
 * （任务卡 DoD 规范检查项）。
 * **原型的「数据备份」卡片也未实现**——后端没有对应接口，
 * 任务卡与 API 设计均未定义该功能，不擅自增加。
 */
import { Tabs, Typography } from 'antd';

import { AdminPanel } from './AdminPanel';
import { RolePanel } from './RolePanel';
import { SiteSettingsPanel } from './SiteSettingsPanel';

export default function SettingsPage() {
  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        系统设置
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginTop: -8 }}>
        站点基础配置、管理员账号与角色权限管理。
      </Typography.Paragraph>

      <Tabs
        defaultActiveKey="site"
        items={[
          {
            key: 'site',
            label: '基础设置',
            children: <SiteSettingsPanel />,
          },
          {
            key: 'admins',
            label: '管理员管理',
            children: <AdminPanel />,
          },
          {
            key: 'roles',
            label: '角色权限',
            children: <RolePanel />,
          },
        ]}
      />
    </div>
  );
}
