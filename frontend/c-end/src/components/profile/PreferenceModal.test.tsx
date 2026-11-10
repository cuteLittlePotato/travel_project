/**
 * 旅游偏好弹窗的测试。
 *
 * 背景：用户反馈「偏好设置编辑后保存报错」。后端 `/me/profile` 实测
 * 返回 204、数据已落库，因此问题在前端。本测试覆盖提交链路，
 * 并验证**错误信息不被吞掉**（原来非 UserApiError 一律显示
 * 「保存失败，请重试」，真实原因不可见）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';

import { PreferenceModal } from './PreferenceModal';
import { UserApiError } from '@/services/user';
import type { TravelProfile } from '@/services/user';

const mockUpdateTravelProfile = vi.fn();

vi.mock('@/components/common/RegionCascader', () => ({
  RegionCascader: ({
    value,
    onChange,
    placeholder,
  }: {
    value?: string | null;
    onChange?: (v: string | null) => void;
    placeholder?: string;
  }) => (
    <select
      aria-label="地区选择器"
      value={value ?? ''}
      onChange={(e) => onChange?.(e.target.value || null)}
    >
      <option value="">{placeholder ?? '选择'}</option>
      <option value="110100">北京市</option>
      <option value="330100">杭州市</option>
    </select>
  ),
}));

vi.mock('@/services/user', async () => {
  const actual = await vi.importActual<typeof import('@/services/user')>(
    '@/services/user',
  );
  return {
    ...actual,
    updateTravelProfile: (...args: unknown[]) => mockUpdateTravelProfile(...args),
  };
});

const PROFILE: TravelProfile = {
  travel_types: ['历史人文'],
  travel_styles: ['深度游'],
  budget_level: 'economy',
  companion_type: 'solo',
  preferred_seasons: ['春季'],
  departure_city_code: null,
  departure_city_info: null,
};

/** 兼容两种调用：传回调（旧用例）或传 profile 覆盖值（新用例） */
function renderModal(arg?: (() => void) | Partial<TravelProfile>) {
  const input: (() => void) | Partial<TravelProfile> = arg ?? (() => {});
  const isProfile = typeof input === 'object';
  const profile = isProfile ? { ...PROFILE, ...input } : PROFILE;
  const callback = isProfile ? vi.fn() : input;

  return render(
    <ConfigProvider locale={zhCN}>
      <AntdApp>
        <PreferenceModal
          open
          profile={profile}
          onCancel={vi.fn()}
          onSuccess={callback}
        />
      </AntdApp>
    </ConfigProvider>,
  );
}

describe('PreferenceModal', () => {
  beforeEach(() => {
    mockUpdateTravelProfile.mockReset();
  });

  it('回显已有偏好', async () => {
    renderModal();

    await waitFor(() => {
      expect(screen.getByText('历史人文')).toBeInTheDocument();
    });
  });

  it('保存时提交完整对象（整体替换语义）', async () => {
    mockUpdateTravelProfile.mockResolvedValue(undefined);
    const onSuccess = vi.fn();
    const user = userEvent.setup();

    renderModal(onSuccess);

    await user.click(screen.getByRole('button', { name: /保\s*存/ }));

    await waitFor(() => {
      expect(mockUpdateTravelProfile).toHaveBeenCalled();
    });

    const payload = mockUpdateTravelProfile.mock.calls[0]?.[0] as TravelProfile;
    // 六个字段必须全部传，否则后端会把未传的清空
    expect(payload).toHaveProperty('travel_types');
    expect(payload).toHaveProperty('travel_styles');
    expect(payload).toHaveProperty('budget_level');
    expect(payload).toHaveProperty('companion_type');
    expect(payload).toHaveProperty('preferred_seasons');
    expect(payload).toHaveProperty('departure_city_code');
  });

  it('保存成功后回调 onSuccess', async () => {
    mockUpdateTravelProfile.mockResolvedValue(undefined);
    const onSuccess = vi.fn();
    const user = userEvent.setup();

    renderModal(onSuccess);

    await user.click(screen.getByRole('button', { name: /保\s*存/ }));

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalled();
    });
  });

  describe('错误展示', () => {
    it('UserApiError 展示后端文案', async () => {
      mockUpdateTravelProfile.mockRejectedValue(
        new UserApiError(10001, '参数校验失败'),
      );
      const user = userEvent.setup();

      renderModal();

      await user.click(screen.getByRole('button', { name: /保\s*存/ }));

      await waitFor(() => {
        expect(screen.getByText('参数校验失败')).toBeInTheDocument();
      });
    });

    it('**UserApiError 的 message 为空时回退到通用文案**', async () => {
      // 真实场景：后端返回 204 无响应体，unwrap 的旧实现把 data.code 的
      // undefined 当成失败，抛出 new UserApiError(undefined, undefined)。
      // 前端 message.error(undefined) 的结果是「只有红叉、没有文字」的空提示。
      mockUpdateTravelProfile.mockRejectedValue(
        new UserApiError(undefined as unknown as number, ''),
      );
      const user = userEvent.setup();

      renderModal();

      await user.click(screen.getByRole('button', { name: /保\s*存/ }));

      await waitFor(() => {
        expect(screen.getByText('保存失败，请重试')).toBeInTheDocument();
      });
    });

    it('未知异常回退到通用文案', async () => {
      mockUpdateTravelProfile.mockRejectedValue('字符串异常');
      const user = userEvent.setup();

      renderModal();

      await user.click(screen.getByRole('button', { name: /保\s*存/ }));

      await waitFor(() => {
        expect(screen.getByText('保存失败，请重试')).toBeInTheDocument();
      });
    });

    it('失败时不调用 onSuccess', async () => {
      mockUpdateTravelProfile.mockRejectedValue(
        new UserApiError(10001, '参数校验失败'),
      );
      const onSuccess = vi.fn();
      const user = userEvent.setup();

      renderModal(onSuccess);

      await user.click(screen.getByRole('button', { name: /保\s*存/ }));

      await waitFor(() => {
        expect(screen.getByText('参数校验失败')).toBeInTheDocument();
      });
      expect(onSuccess).not.toHaveBeenCalled();
    });
  });
});


describe('PreferenceModal —— 默认出发城市', () => {
  beforeEach(() => {
    mockUpdateTravelProfile.mockReset();
  });

  it('**用选择器而非手填**（与常驻地区保持一致，存编码）', () => {
    renderModal();

    // 不再是 Input，而是地区选择器
    expect(screen.getByLabelText('地区选择器')).toBeInTheDocument();
  });

  it('回显已有出发城市', async () => {
    renderModal({ departure_city_code: '330100' });

    await waitFor(() => {
      expect(screen.getByLabelText('地区选择器')).toHaveValue('330100');
    });
  });

  it('选择后提交城市名', async () => {
    mockUpdateTravelProfile.mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderModal();

    await user.selectOptions(screen.getByLabelText('地区选择器'), '110100');
    await user.click(screen.getByRole('button', { name: /保\s*存/ }));

    await waitFor(() => {
      expect(mockUpdateTravelProfile).toHaveBeenCalled();
    });
    const payload = mockUpdateTravelProfile.mock.calls[0]?.[0] as {
      departure_city_code: string | null;
    };
    expect(payload.departure_city_code).toBe('110100');
  });
});
