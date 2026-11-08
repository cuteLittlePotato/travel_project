/**
 * B 端全局错误边界。
 *
 * 渲染期异常（如组件崩溃）在这里兜底，避免整页白屏。
 * 接口错误由 Axios 拦截器统一 Toast，不走这里。
 */
import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Button, Result } from 'antd';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // 生产环境应上报到监控系统；此处先输出到控制台
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  private readonly handleReset = (): void => {
    this.setState({ error: null });
    window.location.reload();
  };

  override render(): ReactNode {
    if (this.state.error) {
      return (
        <Result
          status="error"
          title="页面出错了"
          subTitle={
            import.meta.env.DEV
              ? this.state.error.message
              : '请刷新页面重试，若持续出现请联系技术支持。'
          }
          extra={
            <Button type="primary" onClick={this.handleReset}>
              刷新页面
            </Button>
          }
        />
      );
    }

    return this.props.children;
  }
}
