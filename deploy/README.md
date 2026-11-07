# 部署说明

## 目录约定（测试服务器 192.168.75.100）

```
/opt/travel/
├── deploy/
│   ├── compose.yaml          # 基础设施编排（13 个服务）
│   ├── compose.app.yaml      # 业务应用编排（本仓库 docker-compose.app.yml 部署至此）
│   ├── .env                  # 基础设施环境变量
│   └── .env.app              # 业务应用环境变量
├── app/                      # 本仓库源码（backend / frontend / pyproject.toml）
├── nginx/travel.conf         # Nginx 配置
├── litellm/config.yaml
└── clickhouse/langfuse-user.xml
```

## Nginx 需要增加的两处改动

现有 `/opt/travel/nginx/travel.conf` 已能路由 `/api`、`/admin`、`/`，
但 B 端静态文件目录没有挂载。需要：

1. **挂载共享卷**：在 `compose.yaml` 的 `travel-nginx` 服务中增加
   ```yaml
   volumes:
     - ../nginx/travel.conf:/etc/nginx/conf.d/default.conf:ro
     - travel_b_end_dist:/usr/share/nginx/admin:ro   # 新增
   ```
   并在顶层 `volumes` 增加 `travel_b_end_dist:`（外部卷，由 app 编排创建）。

2. **替换配置**：用本仓库 `deploy/nginx.travel.conf` 覆盖
   `/opt/travel/nginx/travel.conf`，新增 `/health` 健康检查与
   `/api/v1/chat/stream` 的 SSE 专用 location（关闭缓冲、超时 1800s）。

## 部署步骤

```bash
# 1. 同步源码
rsync -az --exclude node_modules --exclude .venv --exclude .next --exclude dist \
  ./ root@192.168.75.100:/opt/travel/app/

# 2. 准备应用环境变量（首次）
cd /opt/travel/deploy
cp /opt/travel/app/.env.app.example .env.app
vi .env.app      # 填写 JWT_SECRET_KEY、各服务密码

# 3. 构建并启动业务容器
docker compose -f compose.yaml -f compose.app.yaml up -d --build

# 4. 验证
curl http://192.168.75.100/api/health
curl -I http://192.168.75.100/
curl -I http://192.168.75.100/admin/
```

## 端口

| 服务 | 宿主端口 |
|---|---|
| Nginx（统一入口） | 80 |
| API（直连调试） | 18000 |
| C 端（直连调试） | 13001 |
| PostgreSQL | 15432 |
| Redis | 16379 |
| Neo4j Bolt / HTTP | 17687 / 17474 |
| Milvus | 19530 |
| Elasticsearch | 19200 |
| MinIO API / Console | 19000 / 19001 |
| RabbitMQ / 管理台 | 5672 / 15672 |
| Langfuse | 13000 |
| LiteLLM | 14000 |

## 数据库初始化

```bash
# 首次：执行 schema.sql（43 张表）
docker exec -i travel-postgres psql -U travel -d travel < /opt/travel/app/scripts/sql/schema.sql

# 或使用 Alembic（M0-T13 完成后）
docker exec travel-api alembic upgrade head
```

## 当前部署状态（2026-11-07 验证通过）

全部业务容器 healthy，三条路由均返回 200：

```
travel-api             Up (healthy)
travel-celery-worker   Up (healthy)
travel-celery-beat     Up (healthy)
travel-frontend        Up (healthy)
travel-b-end           Up
travel-nginx           Up (healthy)
```

| 检查项 | 结果 |
|---|---|
| `GET http://192.168.75.100/api/health` | `{"code":0,"data":{"status":"ok"}}` |
| `GET http://192.168.75.100/api/health/ready` | postgres/redis/milvus/neo4j/elasticsearch/minio 全部 `true` |
| `GET http://192.168.75.100/` | 200（C 端 Next.js） |
| `GET http://192.168.75.100/admin/` | 200（B 端 SPA） |
| `GET http://192.168.75.100/health` | 200（Nginx 存活） |
| Celery worker | 已连接 RabbitMQ，注册 `recalculate_popularity` |
| Celery beat | 定时任务按点触发 |

### 本次部署中做的环境调整

1. **`compose.yaml` 改动**（已备份 `compose.yaml.bak2`）
   - `travel-nginx` 增加卷 `travel_b_end_dist:/usr/share/nginx/admin:ro`
   - 顶层 `volumes` 增加 `travel_b_end_dist`（`name: travel_b_end_dist`）
   - nginx 健康检查从 `localhost` 改为 `127.0.0.1`（IPv6 解析问题）
2. **`/opt/travel/nginx/travel.conf` 替换**为 `deploy/nginx.travel.conf`
3. **MinIO 创建桶** `travel-documents`
4. **`.env.app`** 由基础设施 `.env` 复用密码生成，`JWT_SECRET_KEY` 随机生成

### 弱网环境的构建方式

服务器访问 PyPI 约 38~50 kB/s，直接 `docker build` 会卡在 `uv sync`。
采用**预下载 wheel 离线安装**：

```bash
# 一次性：把依赖 wheel 下载到 /opt/travel/app/.wheels
python3 -m pip download -r /tmp/req.txt -d /opt/travel/app/.wheels

# 之后每次构建都走离线安装
docker build --build-arg WHEEL_DIR=/app/.wheels -f backend/Dockerfile -t travel-backend:dev /opt/travel/app
```

前端镜像已配置 npmmirror 源，构建正常。
