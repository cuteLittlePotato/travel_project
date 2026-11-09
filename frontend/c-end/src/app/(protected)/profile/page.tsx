'use client';

/**
 * C 端个人中心（M01-T17）。
 *
 * 四个区块，与原型 `prototype/c-end/profile.html` 一致（2026-11-08 确认）：
 *   1. 基本信息（昵称/用户名/性别/地区/头像）
 *   2. 旅游偏好（类型/风格/预算标签）
 *   3. 账号绑定（三种第三方 + 手机/邮箱）
 *   4. 其他操作（修改密码 / 隐私设置 / 退出登录）
 *
 * **不做额度展示**——原型无此区块，且额度接口属 M13 未开发。
 */
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  App,
  Avatar,
  Button,
  Card,
  Descriptions,
  Divider,
  Empty,
  Popconfirm,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import { UserOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { EditProfileModal } from '@/components/profile/EditProfileModal';
import { PreferenceModal } from '@/components/profile/PreferenceModal';
import { PrivacyModal } from '@/components/profile/PrivacyModal';
import { ChangePasswordModal } from '@/components/profile/ChangePasswordModal';
import { DeactivateAccountModal } from '@/components/profile/DeactivateAccountModal';
import {
  getProfile,
  getSettings,
  getTravelProfile,
  type BudgetLevel,
  type CompanionType,
} from '@/services/user';
import { logout } from '@/services/auth';
import { useAuthStore } from '@/stores/auth';

/** 枚举 → 中文展示 */
const GENDER_LABEL: Record<string, string> = {
  male: '男',
  female: '女',
  secret: '保密',
};

const BUDGET_LABEL: Record<BudgetLevel, string> = {
  economy: '经济预算',
  moderate: '中等预算',
  comfortable: '舒适预算',
  luxury: '豪华预算',
};

const COMPANION_LABEL: Record<CompanionType, string> = {
  solo: '独自旅行',
  couple: '情侣出游',
  family: '家庭出游',
  friends: '朋友同行',
};

/** Query key 集中管理，避免各处手写字符串 */
const QUERY_KEYS = {
  profile: ['user', 'profile'] as const,
  travelProfile: ['user', 'travel-profile'] as const,
  settings: ['user', 'settings'] as const,
};

type ModalKind =
  | 'edit'
  | 'preference'
  | 'privacy'
  | 'password'
  | 'deactivate'
  | null;

export default function ProfilePage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  const clearAuth = useAuthStore((state) => state.clear);

  const [activeModal, setActiveModal] = useState<ModalKind>(null);

  // ---------- 数据 ----------
  const profileQuery = useQuery({
    queryKey: QUERY_KEYS.profile,
    queryFn: getProfile,
  });

  const travelQuery = useQuery({
    queryKey: QUERY_KEYS.travelProfile,
    queryFn: getTravelProfile,
  });

  const settingsQuery = useQuery({
    queryKey: QUERY_KEYS.settings,
    queryFn: getSettings,
  });

  // ---------- 登出 ----------
  const logoutMutation = useMutation({
    mutationFn: logout,
    onSettled: () => {
      // 无论后端是否成功，本地状态一律清空
      clearAuth();
      queryClient.clear();
      message.success('已退出登录');
      router.replace('/login');
    },
  });

  // ---------- 加载与错误 ----------
  if (profileQuery.isLoading) {
    return (
      <div className="page-container" style={{ paddingTop: 64, textAlign: 'center' }}>
        <Spin size="large" />
      </div>
    );
  }

  if (profileQuery.isError || !profileQuery.data) {
    return (
      <div className="page-container" style={{ paddingTop: 64 }}>
        <Empty description="加载失败，请刷新重试" />
      </div>
    );
  }

  const profile = profileQuery.data;
  const travel = travelQuery.data;
  const settings = settingsQuery.data;

  /** 三个模态框保存成功后统一刷新 */
  const invalidateAll = () => {
    void queryClient.invalidateQueries({ queryKey: ['user'] });
  };

  return (
    <div className="page-container" style={{ paddingTop: 32, paddingBottom: 64 }}>
      {/* ---------- 1. 基本信息 ---------- */}
      <Card style={{ marginBottom: 16 }}>
        <Space align="start" size={24} style={{ marginBottom: 24 }}>
          <Avatar
            size={80}
            src={profile.avatar_url ?? undefined}
            icon={<UserOutlined />}
          />
          <div>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {profile.nickname}
            </Typography.Title>
            <Typography.Text type="secondary">@{profile.username}</Typography.Text>
          </div>
        </Space>

        <Descriptions column={2} size="small">
          <Descriptions.Item label="性别">
            {profile.gender ? GENDER_LABEL[profile.gender] ?? profile.gender : '未设置'}
          </Descriptions.Item>
          <Descriptions.Item label="常驻地区">
            {profile.region?.display || profile.region_code || '未设置'}
          </Descriptions.Item>
          <Descriptions.Item label="注册时间">
            {new Date(profile.created_at).toLocaleDateString('zh-CN')}
          </Descriptions.Item>
        </Descriptions>

        <Divider />
        <Button type="primary" onClick={() => setActiveModal('edit')}>
          编辑资料
        </Button>
      </Card>

      {/* ---------- 2. 旅游偏好 ---------- */}
      <Card title="❤️ 旅游偏好" style={{ marginBottom: 16 }}>
        {travelQuery.isLoading ? (
          <Spin />
        ) : travel ? (
          <>
            <PreferenceRow label="喜欢的类型" values={travel.travel_types} />
            <PreferenceRow label="旅行风格" values={travel.travel_styles} />
            <PreferenceRow
              label="预算偏好"
              values={travel.budget_level ? [BUDGET_LABEL[travel.budget_level]] : []}
            />
            <PreferenceRow
              label="同行人类型"
              values={
                travel.companion_type ? [COMPANION_LABEL[travel.companion_type]] : []
              }
            />
            <PreferenceRow label="偏好季节" values={travel.preferred_seasons} />
            {travel.departure_city && (
              <PreferenceRow label="默认出发城市" values={[travel.departure_city]} />
            )}
            <Divider />
            <Button onClick={() => setActiveModal('preference')}>编辑偏好</Button>
          </>
        ) : (
          <Empty description="暂无偏好设置" />
        )}
      </Card>

      {/* ---------- 3. 账号绑定 ---------- */}
      <Card title="🔗 账号绑定" style={{ marginBottom: 16 }}>
        <Descriptions column={1} size="small">
          {profile.bindings.map((binding) => (
            <Descriptions.Item
              key={`${binding.provider}:${binding.provider_uid}`}
              label={providerLabel(binding.provider)}
            >
              <Tag color="green">✓ 已绑定</Tag>
              <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                {binding.provider_uid}
              </Typography.Text>
              {binding.is_primary && (
                <Tag color="blue" style={{ marginLeft: 8 }}>
                  主方式
                </Tag>
              )}
            </Descriptions.Item>
          ))}
        </Descriptions>
        {profile.bindings.length === 0 && <Empty description="暂无绑定方式" />}
      </Card>

      {/* ---------- 4. 其他操作 ---------- */}
      <Card title="⚙️ 其他操作">
        <Space wrap>
          <Button onClick={() => setActiveModal('password')}>修改密码</Button>
          <Button onClick={() => setActiveModal('privacy')} disabled={!settings}>
            隐私设置
          </Button>
          <Popconfirm
            title="确定要退出登录吗？"
            description="退出后需要重新登录，所有设备都会退出"
            onConfirm={() => logoutMutation.mutate()}
            okText="退出"
            cancelText="取消"
          >
            <Button danger loading={logoutMutation.isPending}>
              退出登录
            </Button>
          </Popconfirm>
        </Space>

        <Divider style={{ margin: '16px 0 12px' }} />

        <Space orientation="vertical" size={4}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            注销账号将永久删除你的数据，且无法恢复
          </Typography.Text>
          <Button danger type="link" onClick={() => setActiveModal('deactivate')}>
            注销账号
          </Button>
        </Space>
      </Card>

      {/* ---------- 模态框 ---------- */}
      {activeModal === 'edit' && (
        <EditProfileModal
          open
          profile={profile}
          onCancel={() => setActiveModal(null)}
          onSuccess={() => {
            setActiveModal(null);
            invalidateAll();
          }}
        />
      )}

      {activeModal === 'preference' && travel && (
        <PreferenceModal
          open
          profile={travel}
          onCancel={() => setActiveModal(null)}
          onSuccess={() => {
            setActiveModal(null);
            invalidateAll();
          }}
        />
      )}

      {activeModal === 'privacy' && settings && (
        <PrivacyModal
          open
          settings={settings}
          onCancel={() => setActiveModal(null)}
          onSuccess={() => {
            setActiveModal(null);
            invalidateAll();
          }}
        />
      )}

      {activeModal === 'deactivate' && (
        <DeactivateAccountModal
          open
          onCancel={() => setActiveModal(null)}
          onSuccess={() => {
            // 注销后 Token 已失效，清空本地状态并回登录页
            clearAuth();
            queryClient.clear();
            router.replace('/login');
          }}
        />
      )}

      {activeModal === 'password' && (
        <ChangePasswordModal
          open
          onCancel={() => setActiveModal(null)}
          onSuccess={() => {
            setActiveModal(null);
            // 改密后所有 Token 失效，需重新登录
            clearAuth();
            queryClient.clear();
            message.success('密码已修改，请重新登录');
            router.replace('/login');
          }}
        />
      )}
    </div>
  );
}

/** 偏好行：标签展示，空值显示「未设置」 */
function PreferenceRow({ label, values }: { label: string; values: string[] }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
        {label}
      </Typography.Text>
      {values.length > 0 ? (
        <Space size={8} wrap>
          {values.map((value) => (
            <Tag key={value} color="blue">
              {value}
            </Tag>
          ))}
        </Space>
      ) : (
        <Typography.Text type="secondary">未设置</Typography.Text>
      )}
    </div>
  );
}

function providerLabel(provider: string): string {
  const map: Record<string, string> = {
    phone: '手机号',
    email: '邮箱',
    wechat: '微信',
    alipay: '支付宝',
    weibo: '微博',
  };
  return map[provider] ?? provider;
}
