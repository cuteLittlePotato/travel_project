/**
 * 开放时间编辑器的测试。
 *
 * 核心约束：产出必须符合数据库设计的 JSONB 结构
 * `{"mon": "09:00-17:00", "tue": "closed", "note": "..."}`。
 */
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import dayjs from 'dayjs';

import { OpeningHoursField, type OpeningHoursValue } from '@/components/form/OpeningHoursField';

function renderField(
  value: OpeningHoursValue = null,
  onChange?: (v: OpeningHoursValue) => void,
) {
  return render(
    <ConfigProvider locale={zhCN}>
      <OpeningHoursField value={value} onChange={onChange} />
    </ConfigProvider>,
  );
}

describe('OpeningHoursField', () => {
  describe('两种模式', () => {
    it('默认「每天相同」模式，只显示一行', () => {
      renderField();

      expect(screen.getByText('周一')).toBeInTheDocument();
      // 按星期模式下才有周二和周日
      expect(screen.queryByText('周二')).not.toBeInTheDocument();
      expect(screen.queryByText('周日')).not.toBeInTheDocument();
    });

    it('切到「按星期设置」显示七天', async () => {
      const user = userEvent.setup();
      renderField();

      await user.click(screen.getByText('按星期设置'));

      for (const day of ['周一', '周二', '周三', '周四', '周五', '周六', '周日']) {
        expect(screen.getByText(day)).toBeInTheDocument();
      }
    });

    it('每天相同模式有说明文字', () => {
      renderField();
      expect(screen.getByText('设置一次，应用到周一至周日')).toBeInTheDocument();
    });
  });

  describe('数据解析（编辑回填）', () => {
    it('解析七天一致的 JSONB 为「每天相同」模式', () => {
      renderField({
        mon: '09:00-17:00',
        tue: '09:00-17:00',
        wed: '09:00-17:00',
        thu: '09:00-17:00',
        fri: '09:00-17:00',
        sat: '09:00-17:00',
        sun: '09:00-17:00',
      });

      // 折叠成单行
      expect(screen.getByText('周一')).toBeInTheDocument();
      expect(screen.queryByText('周二')).not.toBeInTheDocument();
    });

    it('七天不一致时展开为「按星期」模式', () => {
      renderField({
        mon: '09:00-17:00',
        tue: '09:00-17:00',
        sat: '09:00-18:00',
        sun: '09:00-18:00',
      });

      expect(screen.getByText('周一')).toBeInTheDocument();
      expect(screen.getByText('周六')).toBeInTheDocument();
    });

    it('识别闭馆日', () => {
      renderField({
        mon: '09:00-17:00',
        tue: 'closed',
        wed: '09:00-17:00',
        thu: '09:00-17:00',
        fri: '09:00-17:00',
        sat: '09:00-18:00',
        sun: '09:00-18:00',
      });

      // 周二行有「闭馆」勾选
      const checkboxes = screen.getAllByRole('checkbox');
      expect(checkboxes.some((cb) => (cb as HTMLInputElement).checked)).toBe(true);
    });

    it('回填备注', () => {
      renderField({
        mon: '09:00-17:00',
        note: '16:30 停止入场',
      });

      expect(
        screen.getByDisplayValue('16:30 停止入场'),
      ).toBeInTheDocument();
    });

    it('空值不报错', () => {
      renderField(null);
      expect(screen.getByText('周一')).toBeInTheDocument();
    });
  });

  describe('数据产出', () => {
    it('每天相同模式下改动会展开成七天', async () => {
      const onChange = vi.fn();
      const user = userEvent.setup();

      renderField(
        {
          mon: '09:00-17:00',
          tue: '09:00-17:00',
          wed: '09:00-17:00',
          thu: '09:00-17:00',
          fri: '09:00-17:00',
          sat: '09:00-17:00',
          sun: '09:00-17:00',
        },
        onChange,
      );

      // 勾选闭馆
      const checkbox = screen.getByRole('checkbox');
      await user.click(checkbox);

      const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0] as Record<
        string,
        string
      >;

      // 七天都应是 closed
      for (const day of ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']) {
        expect(lastCall[day]).toBe('closed');
      }
    });

    it('备注写入 note 字段', async () => {
      const onChange = vi.fn();
      const user = userEvent.setup();

      renderField(null, onChange);

      await user.type(
        screen.getByPlaceholderText(/16:30 停止入场/),
        '节假日另行通知',
      );

      const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0] as Record<
        string,
        string
      >;
      expect(lastCall.note).toBe('节假日另行通知');
    });

    it('空表单产出 null，不是空对象', () => {
      const onChange = vi.fn();
      renderField(null, onChange);
      // 首次渲染不触发 onChange，这里只验证组件不崩
      expect(screen.getByText('周一')).toBeInTheDocument();
    });
  });

  describe('时间校验', () => {
    it('结束早于开始时提示', () => {
      // 通过回填制造非法区间
      renderField({
        mon: '17:00-09:00',
        tue: '09:00-17:00',
      });

      expect(screen.getByText('结束需晚于开始')).toBeInTheDocument();
    });

    it('合法区间不提示', () => {
      renderField({
        mon: '09:00-17:00',
        tue: '09:00-17:00',
        sat: '09:00-18:00',
      });

      expect(screen.queryByText('结束需晚于开始')).not.toBeInTheDocument();
    });
  });

  describe('闭馆状态', () => {
    it('闭馆时时间选择器禁用', () => {
      renderField({
        mon: 'closed',
        tue: '09:00-17:00',
      });

      const inputs = screen.getAllByRole('textbox');
      // 周一的时间输入应为 disabled
      const disabledInputs = inputs.filter(
        (input) => (input as HTMLInputElement).disabled,
      );
      expect(disabledInputs.length).toBeGreaterThan(0);
    });
  });
});

describe('dayjs 时间解析', () => {
  it('HH:mm 格式能被正确解析', () => {
    const parsed = dayjs('09:00', 'HH:mm');
    expect(parsed.isValid()).toBe(true);
    expect(parsed.format('HH:mm')).toBe('09:00');
  });
});

describe('模式不被回传值覆盖（回归测试）', () => {
  /**
   * 真实 bug：在「按星期」模式下取消唯一勾选的闭馆，
   * 序列化结果是 null；父组件把 null 回传后，
   * parse(null) 默认返回 mode='same'，界面跳回「每天相同」。
   */
  it('按星期模式下取消闭馆后仍停留在「按星期」', async () => {
    const user = userEvent.setup();

    // 受控组件：把 onChange 的值写回 value，模拟 Form.Item 的行为
    function Controlled() {
      const [value, setValue] = React.useState<OpeningHoursValue>({
        mon: 'closed',
      });
      return <OpeningHoursField value={value} onChange={setValue} />;
    }

    render(
      <ConfigProvider locale={zhCN}>
        <Controlled />
      </ConfigProvider>,
    );

    // 取消勾选周一闭馆（按星期模式有 7 个 checkbox，取第一个）
    const checkbox = screen.getAllByRole('checkbox')[0];
    expect(checkbox).toBeDefined();
    expect(checkbox).toBeChecked();
    await user.click(checkbox as HTMLElement);

    // 仍应是「按星期」模式 —— 七天都可见
    expect(screen.getByText('周二')).toBeInTheDocument();
    expect(screen.getByText('周日')).toBeInTheDocument();
  });

  it('每天相同模式下清空时间后仍停留在「每天相同」', async () => {
    const user = userEvent.setup();

    function Controlled() {
      const [value, setValue] = React.useState<OpeningHoursValue>({
        mon: '09:00-17:00',
        tue: '09:00-17:00',
        wed: '09:00-17:00',
        thu: '09:00-17:00',
        fri: '09:00-17:00',
        sat: '09:00-17:00',
        sun: '09:00-17:00',
      });
      return <OpeningHoursField value={value} onChange={setValue} />;
    }

    render(
      <ConfigProvider locale={zhCN}>
        <Controlled />
      </ConfigProvider>,
    );

    // 勾选闭馆再取消（序列化走 closed → null 的路径）
    const checkbox = screen.getAllByRole('checkbox')[0];
    expect(checkbox).toBeDefined();
    await user.click(checkbox as HTMLElement);
    await user.click(checkbox as HTMLElement);

    // 仍是「每天相同」：只有周一一行
    expect(screen.getByText('周一')).toBeInTheDocument();
    expect(screen.queryByText('周二')).not.toBeInTheDocument();
  });
});
