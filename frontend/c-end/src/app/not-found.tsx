/**
 * 全局 404 页面。
 */
import Link from 'next/link';
import { Button, Result } from 'antd';

export default function NotFound() {
  return (
    <div className="page-container" style={{ paddingTop: 96 }}>
      <Result
        status="404"
        title="页面不存在"
        subTitle="你访问的页面可能已被移除或地址有误。"
        extra={
          <Link href="/">
            <Button type="primary">返回首页</Button>
          </Link>
        }
      />
    </div>
  );
}
