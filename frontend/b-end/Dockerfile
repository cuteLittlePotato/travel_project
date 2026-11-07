# ============================================
# B 端 Vite SPA 镜像
# 构建为静态文件，由 Nginx 托管在 /admin/
# 构建上下文：frontend/b-end
# ============================================
FROM node:20-alpine AS builder
WORKDIR /app

RUN npm config set registry https://registry.npmmirror.com

ARG VITE_API_BASE_URL=/api/v1/admin
ARG VITE_PUBLIC_PATH=/admin/
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_PUBLIC_PATH=$VITE_PUBLIC_PATH

COPY package.json package-lock.json* ./
RUN npm ci || npm install

COPY . .
RUN npm run build


FROM nginx:1.27-alpine AS runtime
# 容器只作为构建产物的载体，文件由 Nginx 通过共享卷读取
COPY --from=builder /app/dist /usr/share/nginx/admin
CMD ["nginx", "-g", "daemon off;"]
