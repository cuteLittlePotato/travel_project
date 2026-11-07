/**
 * 占位页。
 *
 * 基础工程阶段用于验证路由与布局；各业务页在对应模块任务完成后替换。
 */
import { Empty, Typography } from 'antd';

export function PlaceholderPage({ title }: { title: string }) {
  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        {title}
      </Typography.Title>
      <Empty description={`${title}（待实现）`} style={{ marginTop: 96 }} />
    </div>
  );
}
