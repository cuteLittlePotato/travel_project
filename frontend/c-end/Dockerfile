# ============================================
# C 端 Next.js 镜像（standalone 输出）
# 构建上下文：frontend/c-end
# ============================================
FROM node:20-alpine AS builder
WORKDIR /app

# 国内镜像加速依赖安装
RUN npm config set registry https://registry.npmmirror.com

COPY package.json package-lock.json* ./
RUN npm ci || npm install

COPY . .

# 构建期后端地址（SSR 使用），路由重写与 standalone 产物一并生成
ARG API_INTERNAL_BASE_URL=http://travel-api:8000
ENV API_INTERNAL_BASE_URL=$API_INTERNAL_BASE_URL \
    NEXT_TELEMETRY_DISABLED=1

RUN npm run build


FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "require('http').get('http://127.0.0.1:3000/',r=>process.exit(r.statusCode<500?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "server.js"]
