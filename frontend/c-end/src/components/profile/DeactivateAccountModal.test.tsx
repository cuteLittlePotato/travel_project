/**
 * 账号注销弹窗的测试。
 *
 * 核心约束：
 *   - 必须输入正确的密码
 *   - 必须手动输入「注销」二字
 *   - 说明清楚后果（不可恢复、清理什么、保留什么）
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';

import { DeactivateAccountModal } from './DeactivateAccountModal';
import { UserApiError } from '@/services/user';

const mockDeactivate = vi.fn();

vi.mock('@/services/user', async () => {
  const actual = await vi.importActual<typeof import('@/services/user')>(
    '@/services/user',
  );
  return {
    ...actual,
    deactivateAccount: (...args: unknown[]) => mockDeactivate(...args),
  };
});

function renderModal(onSuccess = vi.fn()) {
  return render(
    <ConfigProvider locale={zhCN}>
      <AntdApp>
        <DeactivateAccountModal
          open
          onCancel={vi.fn()}
          onSuccess={onSuccess}
        />
      </AntdApp>
    </ConfigProvider>,
  );
}

describe('DeactivateAccountModal', () => {
  beforeEach(() => {
    mockDeactivate.mockReset();
  });

  describe('后果说明', () => {
    it('提示不可恢复', () => {
      renderModal();
      expect(screen.getByText('此操作不可恢复')).toBeInTheDocument();
    });

    it('说明会清理什么', () => {
      renderModal();

      expect(screen.getByText(/所有设备立即退出登录/)).toBeInTheDocument();
      expect(screen.getByText(/对话记录、长期记忆、额度记录被清除/)).toBeInTheDocument();
    });

    it('说明会保留什么', () => {
      renderModal();
      expect(
        screen.getByText(/足迹保留但作者显示为「已注销用户」/),
      ).toBeInTheDocument();
    });

    it('注销按钮是危险样式', () => {
      renderModal();
      const okButton = screen.getByRole('button', { name: /确认注销/ });
      expect(okButton.className).toContain('ant-btn-dangerous');
    });
  });

  describe('表单校验', () => {
    it('密码为空时不提交', async () => {
      const user = userEvent.setup();
      renderModal();

      await user.click(screen.getByRole('button', { name: /确认注销/ }));

      await waitFor(() => {
        expect(screen.getByText('请输入密码')).toBeInTheDocument();
      });
      expect(mockDeactivate).not.toHaveBeenCalled();
    });

    it('确认文字为空时不提交', async () => {
      const user = userEvent.setup();
      renderModal();

      await user.type(screen.getByPlaceholderText('请输入当前密码'), 'Passw0rd1');
      await user.click(screen.getByRole('button', { name: /确认注销/ }));

      await waitFor(() => {
        expect(screen.getByText('请输入「注销」')).toBeInTheDocument();
      });
      expect(mockDeactivate).not.toHaveBeenCalled();
    });

    it('确认文字不是「注销」时拒绝', async () => {
      const user = userEvent.setup();
      renderModal();

      await user.type(screen.getByPlaceholderText('请输入当前密码'), 'Passw0rd1');
      await user.type(screen.getByPlaceholderText('注销'), '确定');
      await user.click(screen.getByRole('button', { name: /确认注销/ }));

      await waitFor(() => {
        expect(screen.getByText('请准确输入「注销」两个字')).toBeInTheDocument();
      });
      expect(mockDeactivate).not.toHaveBeenCalled();
    });

    it('两个都填对才提交', async () => {
      mockDeactivate.mockResolvedValue(undefined);
      const user = userEvent.setup();
      renderModal();

      await user.type(screen.getByPlaceholderText('请输入当前密码'), 'Passw0rd1');
      await user.type(screen.getByPlaceholderText('注销'), '注销');
      await user.click(screen.getByRole('button', { name: /确认注销/ }));

      await waitFor(() => {
        expect(mockDeactivate).toHaveBeenCalledWith({
          password: 'Passw0rd1',
          confirmation: '注销',
        });
      });
    });
  });

  describe('提交结果', () => {
    it('成功后回调 onSuccess', async () => {
      mockDeactivate.mockResolvedValue(undefined);
      const onSuccess = vi.fn();
      const user = userEvent.setup();

      renderModal(onSuccess);

      await user.type(screen.getByPlaceholderText('请输入当前密码'), 'Passw0rd1');
      await user.type(screen.getByPlaceholderText('注销'), '注销');
      await user.click(screen.getByRole('button', { name: /确认注销/ }));

      await waitFor(() => {
        expect(onSuccess).toHaveBeenCalled();
      });
    });

    it('密码错误展示后端文案，不回调', async () => {
      mockDeactivate.mockRejectedValue(
        new UserApiError(11006, '身份验证失败，请确认密码后重试'),
      );
      const onSuccess = vi.fn();
      const user = userEvent.setup();

      renderModal(onSuccess);

      await user.type(screen.getByPlaceholderText('请输入当前密码'), 'WrongPass1');
      await user.type(screen.getByPlaceholderText('注销'), '注销');
      await user.click(screen.getByRole('button', { name: /确认注销/ }));

      await waitFor(() => {
        expect(
          screen.getByText('身份验证失败，请确认密码后重试'),
        ).toBeInTheDocument();
      });
      expect(onSuccess).not.toHaveBeenCalled();
    });

    it('未设密码提示先设置密码', async () => {
      mockDeactivate.mockRejectedValue(
        new UserApiError(11013, '该账号未设置密码，无法验证身份'),
      );
      const user = userEvent.setup();

      renderModal();

      await user.type(screen.getByPlaceholderText('请输入当前密码'), 'AnyPass1');
      await user.type(screen.getByPlaceholderText('注销'), '注销');
      await user.click(screen.getByRole('button', { name: /确认注销/ }));

      await waitFor(() => {
        expect(
          screen.getByText(/该账号未设置密码，无法验证身份/),
        ).toBeInTheDocument();
      });
    });
  });
});
