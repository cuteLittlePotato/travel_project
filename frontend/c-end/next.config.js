/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 容器部署产出独立运行时，镜像体积小
  output: 'standalone',
  poweredByHeader: false,
  eslint: {
    ignoreDuringBuilds: false,
  },
  async rewrites() {
    // 开发期把 /api 代理到后端，避免跨域；生产由 Nginx 分流
    const backend = process.env.API_INTERNAL_BASE_URL || 'http://127.0.0.1:8000';
    return [
      {
        source: '/api/:path*',
        destination: `${backend}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
