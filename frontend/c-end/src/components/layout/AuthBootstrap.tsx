'use client';

/**
 * 挂载登录态探测。放在根布局中，只执行一次。
 */
import { useAuthBootstrap } from '@/hooks/useAuthBootstrap';

export function AuthBootstrap() {
  useAuthBootstrap();
  return null;
}
