# 云游坊（Cloud Travel Workshop）

AI 驱动的旅行推荐与行程规划平台。本仓库包含完整的需求、设计、原型与工程代码。

## 仓库结构

```
travel_project/
├── backend/                 # FastAPI 后端
├── frontend/
│   ├── c-end/               # C 端 Next.js 14（SSR）
│   └── b-end/               # B 端 Vite + React SPA
├── docs/
│   ├── 云游坊-需求文档.md    # 已确认需求
│   ├── design/              # 01 模块梳理 / 02 架构 / 03 数据库 / 04 API / 05 评审
│   ├── tasks/               # 18 份任务清单，213 项任务
│   └── rules/               # 数据库与 API 规范
├── prototype/               # 17 个可交互页面原型（设计参考，不参与构建）
├── scripts/sql/schema.sql   # 43 张表的 DDL
├── docker-compose.app.yml   # 业务容器编排
├── pyproject.toml           # Python 依赖（uv 管理）
└── uv.lock
```

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.x（async） · Alembic · Celery |
| Agent | LangGraph · LangChain · LiteLLM |
| 存储 | PostgreSQL 17 · Redis 7 · Milvus · Elasticsearch（IK） · Neo4j · MinIO · RabbitMQ |
| 可观测 | Langfuse（自托管） |
| 前端 | Next.js 14（C 端 SSR） · Vite + React 18（B 端 SPA） · Ant Design 6 · TanStack Query · Zustand |
| 部署 | Docker Compose · Nginx |

## 快速开始

开发采用**混合模式**：业务服务跑在本机（热重载），中间件用测试服务器上已部署的实例，
避免每次改动都上传服务器重建镜像。详见 [docs/开发环境说明.md](docs/开发环境说明.md)。

```bash
# 1. 后端依赖
uv sync

# 2. 生成 backend/.env（从服务器读取中间件凭据）
python scripts/dev/setup_local_env.py

# 3. 检查到中间件的连通性
python scripts/dev/check_remote_services.py

# 4. 启动（Windows PowerShell）
.\scripts\dev\dev.ps1 api        # 后端  http://localhost:8000/docs
.\scripts\dev\dev.ps1 c-end      # C 端  http://localhost:3000
.\scripts\dev\dev.ps1 b-end      # B 端  http://localhost:5173/admin/

# Git Bash / macOS / Linux
./scripts/dev/dev.sh api
```

前端首次运行需先 `npm install`（脚本会自动处理）。

## 常用命令

```bash
# 后端
uv run pytest                     # 单元测试
uv run ruff check backend/        # 代码检查
cd backend && uv run alembic upgrade head   # 执行迁移

# 前端
npm run typecheck                 # TypeScript 检查
npm run build                     # 生产构建
npm run gen:api                   # 从后端 OpenAPI 生成类型
```

## 测试服务器

- 地址：`192.168.75.100`
- 基础设施：`/opt/travel/deploy/compose.yaml`（13 个服务）
- 业务应用：`/opt/travel/app`，编排文件 `docker-compose.app.yml`

暴露端口（宿主机）：

| 服务 | 端口 |
|---|---|
| PostgreSQL | 15432 |
| Redis | 16379 |
| Neo4j Bolt / HTTP | 17687 / 17474 |
| Milvus | 19530 |
| Elasticsearch | 19200 |
| MinIO API / Console | 19000 / 19001 |
| RabbitMQ / 管理台 | 5672 / 15672 |
| Langfuse | 13000 |
| LiteLLM | 14000 |
| Nginx | 80 |

## 开发规范

- 数据库：[docs/rules/database-rules.md](docs/rules/database-rules.md) — UUIDv7 主键、**禁止物理外键**、snake_case、TIMESTAMPTZ
- API：[docs/rules/api-rules.md](docs/rules/api-rules.md) — REST、`{code, message, data}` 统一响应、语义化 HTTP 状态码
- Python / 前端编码规范：见 [CLAUDE.md](CLAUDE.md)

## 任务计划

`docs/tasks/` 下共 213 项任务、339.5 小时，分 7 个批次推进。
从 `docs/tasks/00.任务总览.md` 开始。
