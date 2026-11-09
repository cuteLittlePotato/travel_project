/**
 * 景点开放时间编辑器。
 *
 * 数据结构与数据库设计一致（`03.数据库设计.md` §3.2）：
 *
 *     {
 *       "mon": "09:00-17:00",
 *       "tue": "09:00-17:00",
 *       "wed": "closed",
 *       "note": "16:30 停止入场"
 *     }
 *
 * 两种录入模式：
 *   - **每天相同**：填一次，展开成 7 天。绝大多数景点是这种。
 *   - **按星期**：逐日设置，可勾选「闭馆」。
 *
 * 为什么用 TimePicker 而不是纯文本：
 *   文本框能表达任意内容，但也意味着格式不统一——C 端要按星期展示
 *   时得为每种写法写解析规则。选择器保证 `HH:mm-HH:mm` 一定是这个格式。
 *   真正无法结构化的内容（停止入场时间等）放 `note`。
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Checkbox, Col, Input, Radio, Row, Space, TimePicker, Typography } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';

/** 一周七天，与后端 JSONB 的 key 对应 */
const WEEKDAYS: { key: string; label: string }[] = [
  { key: 'mon', label: '周一' },
  { key: 'tue', label: '周二' },
  { key: 'wed', label: '周三' },
  { key: 'thu', label: '周四' },
  { key: 'fri', label: '周五' },
  { key: 'sat', label: '周六' },
  { key: 'sun', label: '周日' },
];

const CLOSED = 'closed';
const TIME_FORMAT = 'HH:mm';

/** 单日的编辑态 */
interface DayState {
  /** 是否闭馆 */
  closed: boolean;
  open: Dayjs | null;
  close: Dayjs | null;
}

/** 七天的编辑态。key 固定为 mon..sun，因此用 Record 并保证全覆盖 */
type WeekState = Record<string, DayState>;

const EMPTY_DAY: DayState = { closed: false, open: null, close: null };

const WEEKDAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const;

function emptyWeek(): WeekState {
  const week: WeekState = {};
  for (const key of WEEKDAY_KEYS) {
    week[key] = { ...EMPTY_DAY };
  }
  return week;
}

/** 安全取某天状态（key 一定存在，空值兜底） */
function dayOf(week: WeekState, key: string): DayState {
  return week[key] ?? { ...EMPTY_DAY };
}

/** 同上，但保证非空——供模板里使用，避免每处都判空 */
function requireDay(week: WeekState, key: string): DayState {
  return dayOf(week, key);
}

export type OpeningHoursValue = Record<string, string> | null;

/** 把后端 JSONB 转成编辑器内部状态 */
function parse(value: OpeningHoursValue): {
  mode: 'same' | 'weekly';
  days: Record<string, DayState>;
  note: string;
} {
  const days: WeekState = emptyWeek();

  if (!value) {
    return { mode: 'same', days, note: '' };
  }

  const note = typeof value.note === 'string' ? value.note : '';
  const ranges = WEEKDAYS.map(({ key }) => value[key]).filter(
    (v): v is string => typeof v === 'string',
  );

  // 没有逐日数据，但 note 里像是时间区间 → 当作「每天相同」
  const hasWeekly = ranges.length > 0;

  if (!hasWeekly) {
    return { mode: 'same', days, note };
  }

  for (const { key } of WEEKDAYS) {
    const raw = value[key];
    if (typeof raw !== 'string') continue;
    if (raw === CLOSED) {
      days[key] = { closed: true, open: null, close: null };
      continue;
    }
    const [open, close] = raw.split('-');
    days[key] = {
      closed: false,
      open: open ? dayjs(open, TIME_FORMAT) : null,
      close: close ? dayjs(close, TIME_FORMAT) : null,
    };
  }

  // 七天完全一致 → 折叠成「每天相同」模式，编辑更省事
  const signature = WEEKDAYS.map(({ key }) => {
    const day = dayOf(days, key);
    if (day.closed) return CLOSED;
    if (!day.open || !day.close) return '';
    return `${day.open.format(TIME_FORMAT)}-${day.close.format(TIME_FORMAT)}`;
  });
  const allSame = signature.every((s) => s === signature[0]);
  const mode = allSame && signature[0] !== '' ? 'same' : 'weekly';

  return { mode, days, note };
}

/** 编辑器内部状态 → 后端 JSONB */
function serialize(
  mode: 'same' | 'weekly',
  days: WeekState,
  note: string,
): OpeningHoursValue {
  const result: Record<string, string> = {};

  const encode = (day: DayState): string | null => {
    if (day.closed) return CLOSED;
    if (!day.open || !day.close) return null;
    return `${day.open.format(TIME_FORMAT)}-${day.close.format(TIME_FORMAT)}`;
  };

  if (mode === 'same') {
    // 「每天相同」模式只取周一的值，展开到七天
    const encoded = encode(dayOf(days, 'mon'));
    if (encoded) {
      for (const { key } of WEEKDAYS) result[key] = encoded;
    }
  } else {
    for (const { key } of WEEKDAYS) {
      const encoded = encode(dayOf(days, key));
      if (encoded) result[key] = encoded;
    }
  }

  if (note.trim()) result.note = note.trim();

  return Object.keys(result).length > 0 ? result : null;
}

export interface OpeningHoursFieldProps {
  value?: OpeningHoursValue;
  onChange?: (value: OpeningHoursValue) => void;
}

export function OpeningHoursField({ value, onChange }: OpeningHoursFieldProps) {
  const parsed = useMemo(() => parse(value ?? null), [value]);

  const [mode, setMode] = useState<'same' | 'weekly'>(parsed.mode);
  const [days, setDays] = useState<WeekState>(parsed.days);
  const [note, setNote] = useState(parsed.note);

  // 记录上一次由本组件 emit 出去的值。
  // 它用来区分「外部传入的新值」与「自己刚刚 emit 后被父组件回传的值」——
  // 后者不应重新解析模式，否则用户主动选的「按星期」会被覆盖。
  //
  // 触发过的真实 bug：在「按星期」模式下取消唯一勾选的闭馆，
  // 序列化结果是 null；parse(null) 默认返回 mode='same'，
  // 界面就从「按星期」跳回了「每天相同」。
  const lastEmittedRef = useRef<OpeningHoursValue>(null);

  useEffect(() => {
    // 父组件回传的正是自己刚发出的值 → 忽略，保留用户当前的模式选择
    if (value === lastEmittedRef.current) {
      return;
    }

    const next = parse(value ?? null);
    setMode(next.mode);
    setDays(next.days);
    setNote(next.note);
  }, [value]);

  const emit = (
    nextMode: 'same' | 'weekly',
    nextDays: WeekState,
    nextNote: string,
  ) => {
    const next = serialize(nextMode, nextDays, nextNote);
    lastEmittedRef.current = next;
    onChange?.(next);
  };

  const updateDay = (key: string, patch: Partial<DayState>) => {
    // 「每天相同」模式下改周一，同步到七天
    if (mode === 'same') {
      const next: WeekState = { ...days };
      for (const { key: k } of WEEKDAYS) {
        next[k] = { ...dayOf(days, k), ...patch };
      }
      setDays(next);
      emit(mode, next, note);
      return;
    }

    const next: WeekState = { ...days, [key]: { ...dayOf(days, key), ...patch } };
    setDays(next);
    emit(mode, next, note);
  };

  const switchMode = (nextMode: 'same' | 'weekly') => {
    const nextDays: WeekState = { ...days };
    // 从「按星期」切到「每天相同」时，把周一的值铺到全周
    if (nextMode === 'same') {
      for (const { key } of WEEKDAYS) {
        nextDays[key] = { ...dayOf(days, 'mon') };
      }
    }
    setMode(nextMode);
    setDays(nextDays);
    emit(nextMode, nextDays, note);
  };

  const currentDay = mode === 'same' ? dayOf(days, 'mon') : null;
  const rows = mode === 'same' ? WEEKDAYS.slice(0, 1) : WEEKDAYS;

  return (
    <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 12 }}>
      <Radio.Group
        value={mode}
        onChange={(event) => switchMode(event.target.value)}
        style={{ marginBottom: 12 }}
      >
        <Radio.Button value="same">每天相同</Radio.Button>
        <Radio.Button value="weekly">按星期设置</Radio.Button>
      </Radio.Group>

      {mode === 'same' && (
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 8, fontSize: 12 }}>
          设置一次，应用到周一至周日
        </Typography.Text>
      )}

      <Space orientation="vertical" size={8} style={{ width: '100%' }}>
        {rows.map(({ key, label }) => {
          const day: DayState =
            mode === 'same' && currentDay ? currentDay : requireDay(days, key);

          return (
            <Row key={key} align="middle" gutter={8}>
              <Col span={4}>
                <Typography.Text>{label}</Typography.Text>
              </Col>
              <Col span={14}>
                <Space size={4}>
                  <TimePicker
                    value={day.open}
                    format={TIME_FORMAT}
                    minuteStep={5}
                    placeholder="开始"
                    allowClear={false}
                    disabled={day.closed}
                    onChange={(time) => updateDay(key, { open: time })}
                    style={{ width: 100 }}
                  />
                  <span>至</span>
                  <TimePicker
                    value={day.close}
                    format={TIME_FORMAT}
                    minuteStep={5}
                    placeholder="结束"
                    allowClear={false}
                    disabled={day.closed}
                    onChange={(time) => updateDay(key, { close: time })}
                    style={{ width: 100 }}
                  />
                  {!day.closed && day.open && day.close && !day.close.isAfter(day.open) && (
                    <Typography.Text type="danger" style={{ fontSize: 12 }}>
                      结束需晚于开始
                    </Typography.Text>
                  )}
                </Space>
              </Col>
              <Col span={6}>
                <Checkbox
                  checked={day.closed}
                  onChange={(event) => updateDay(key, { closed: event.target.checked })}
                >
                  闭馆
                </Checkbox>
              </Col>
            </Row>
          );
        })}
      </Space>

      <div style={{ marginTop: 12 }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          备注
        </Typography.Text>
        <Input
          style={{ marginTop: 4 }}
          placeholder="如：16:30 停止入场、法定节假日另行通知"
          value={note}
          maxLength={200}
          onChange={(event) => {
            setNote(event.target.value);
            emit(mode, days, event.target.value);
          }}
        />
      </div>
    </div>
  );
}
