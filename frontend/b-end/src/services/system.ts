/**
 * M15 系统管理服务（API §14.1 ~ §14.13）。
 */
import { request } from '@/services/http';
import type { PageData } from '@/types/api';

// ============================================================
// 站点配置（API §14.12 / §14.13）
// ============================================================

export interface SiteSettings {
  site_name: string;
  site_description: string;
  allow_registration: boolean;
  allow_content_review: boolean;
}

export type SiteSettingsUpdate = Partial<SiteSettings>;

export function getSiteSettings(): Promise<SiteSettings> {
  return request({ url: '/system/settings' });
}

export async function updateSiteSettings(
  payload: SiteSettingsUpdate,
): Promise<void> {
  await request<null>({ url: '/system/settings', method: 'PUT', data: payload });
}

// ============================================================
// 管理员（API §14.1 ~ §14.5）
// ============================================================

export interface RoleBrief {
  id: string;
  code: string;
  name: string;
}

export interface Admin {
  id: string;
  username: string;
  real_name: string | null;
  email: string | null;
  status: 'active' | 'disabled';
  roles: RoleBrief[];
  last_login_at: string | null;
  created_at: string;
}

export interface AdminCreatePayload {
  username: string;
  password: string;
  real_name?: string | null;
  email?: string | null;
  role_ids: string[];
}

export interface AdminUpdatePayload {
  real_name?: string | null;
  email?: string | null;
  role_ids?: string[];
  status?: 'active' | 'disabled';
}

export function listAdmins(params: {
  keyword?: string;
  status?: 'active' | 'disabled';
  page?: number;
  page_size?: number;
}): Promise<PageData<Admin>> {
  return request({ url: '/system/admins', params });
}

export function createAdmin(payload: AdminCreatePayload): Promise<Admin> {
  return request({ url: '/system/admins', method: 'POST', data: payload });
}

export async function updateAdmin(
  id: string,
  payload: AdminUpdatePayload,
): Promise<void> {
  await request<null>({ url: `/system/admins/${id}`, method: 'PATCH', data: payload });
}

export async function resetAdminPassword(
  id: string,
  newPassword: string,
): Promise<void> {
  await request<null>({
    url: `/system/admins/${id}/password`,
    method: 'PUT',
    data: { new_password: newPassword },
  });
}

export async function deleteAdmin(id: string): Promise<void> {
  await request<null>({ url: `/system/admins/${id}`, method: 'DELETE' });
}

// ============================================================
// 角色与权限（API §14.6 ~ §14.10）
// ============================================================

export interface Role {
  id: string;
  code: string;
  name: string;
  description: string | null;
  is_builtin: boolean;
  admin_count: number;
  permission_count: number;
  created_at: string;
  updated_at: string;
}

export interface Permission {
  id: string;
  code: string;
  module: string;
  action: string;
  name: string;
  description: string | null;
}

export interface PermissionGroup {
  module: string;
  permissions: Permission[];
}

export interface RoleDetail extends Role {
  permissions: Permission[];
}

export interface RolePayload {
  code: string;
  name: string;
  description?: string | null;
  permission_ids?: string[];
}

export function listRoles(): Promise<{ items: Role[] }> {
  return request({ url: '/system/roles' });
}

export function getRole(id: string): Promise<RoleDetail> {
  return request({ url: `/system/roles/${id}` });
}

export function createRole(payload: RolePayload): Promise<RoleDetail> {
  return request({ url: '/system/roles', method: 'POST', data: payload });
}

export async function updateRole(
  id: string,
  payload: { name?: string; description?: string | null },
): Promise<void> {
  await request<null>({ url: `/system/roles/${id}`, method: 'PATCH', data: payload });
}

export async function setRolePermissions(
  id: string,
  permissionIds: string[],
): Promise<void> {
  await request<null>({
    url: `/system/roles/${id}/permissions`,
    method: 'PUT',
    data: { permission_ids: permissionIds },
  });
}

export async function deleteRole(id: string): Promise<void> {
  await request<null>({ url: `/system/roles/${id}`, method: 'DELETE' });
}

export function listPermissions(): Promise<{
  items: Permission[];
  groups: PermissionGroup[];
  total: number;
}> {
  return request({ url: '/system/permissions' });
}
