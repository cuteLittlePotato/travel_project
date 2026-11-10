'use client';

/**
 * 快捷操作（原型「🎯 快速操作」区块）。
 *
 * 四个操作中有三个依赖尚未开发的模块：
 *   - 加入计划 → M04
 *   - 标记去过 → M05
 *   - 咨询助手 → M03
 *   - 查看知识图谱 → M10
 *
 * 当前处理：**能确定跳转的做成链接，不能的禁用并说明原因**。
 * 不做「点了没反应」的假按钮——那比禁用更让人困惑。
 */
import Link from 'next/link';

export interface QuickActionsProps {
  attractionId: string;
  attractionName: string;
  isLoggedIn: boolean;
}

interface Action {
  key: string;
  label: string;
  icon: string;
  href?: string;
  disabledReason?: string;
  primary?: boolean;
}

export function QuickActions({
  attractionId,
  attractionName,
  isLoggedIn,
}: QuickActionsProps) {
  const actions: Action[] = [
    {
      key: 'plan',
      label: '加入旅游计划',
      icon: '📅',
      disabledReason: '行程规划功能开发中',
      primary: true,
    },
    {
      key: 'footprint',
      label: '标记为去过',
      icon: '📍',
      disabledReason: '足迹功能开发中',
    },
    {
      key: 'graph',
      label: '查看知识图谱',
      icon: '🕸️',
      href: `/knowledge-graph/${attractionId}`,
    },
    {
      key: 'chat',
      label: '咨询 AI 助手',
      icon: '💬',
      disabledReason: isLoggedIn ? '对话功能开发中' : '登录后可使用',
    },
  ];

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
        gap: 12,
      }}
    >
      {actions.map((action) => {
        const baseStyle: React.CSSProperties = {
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 8,
          padding: '14px 20px',
          borderRadius: 10,
          fontSize: 15,
          fontWeight: 500,
          textDecoration: 'none',
          border: '1px solid var(--color-border)',
        };

        if (action.disabledReason) {
          return (
            <button
              key={action.key}
              type="button"
              disabled
              title={action.disabledReason}
              style={{
                ...baseStyle,
                background: '#f5f5f5',
                color: '#bfbfbf',
                cursor: 'not-allowed',
              }}
            >
              <span>{action.icon}</span>
              {action.label}
            </button>
          );
        }

        return (
          <Link
            key={action.key}
            href={action.href!}
            style={{
              ...baseStyle,
              background: action.primary ? '#1677ff' : '#fff',
              color: action.primary ? '#fff' : 'inherit',
              borderColor: action.primary ? '#1677ff' : 'var(--color-border)',
            }}
            aria-label={`${action.label}：${attractionName}`}
          >
            <span>{action.icon}</span>
            {action.label}
          </Link>
        );
      })}
    </div>
  );
}
