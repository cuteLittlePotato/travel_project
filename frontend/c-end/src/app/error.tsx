'use client';

/**
 * 路由级错误边界。
 *
 * SSR 阶段抛出的异常（如后端不可达）由这里接管，
 * 用户看到友好的降级页面而不是 Next.js 默认错误栈。
 */
import { Button, Result } from 'antd';

export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  // 生产环境不展示具体错误信息，避免泄露内部细节
  const isDev = process.env.NODE_ENV === 'development';

  return (
    <div className="page-container" style={{ paddingTop: 96 }}>
      <Result
        status="warning"
        title="页面暂时无法加载"
        subTitle={
          isDev
            ? error.message
            : '服务可能正在维护，请稍后重试。如果问题持续，请联系客服。'
        }
        extra={
          <Button type="primary" onClick={reset}>
            重新加载
          </Button>
        }
      />
    </div>
  );
}
