# 云游坊后端

FastAPI + SQLAlchemy 2.x + PostgreSQL 的后端工程骨架，按 `docs/design/02.整体架构设计.md` §4.2 组织。

## 目录结构

```
backend/
├── app/
│   ├── main.py              # 应用入口 create_app()
│   ├── core/                # 配置、安全、异常、响应、日志、依赖
│   ├── api/
│   │   ├── router.py        # 总路由注册
│   │   ├── v1/c_end/        # C 端路由（/api/v1/*）
│   │   ├── v1/b_end/        # B 端路由（/api/v1/admin/*）
│   │   └── middleware/      # 认证、权限、日志、限流
│   ├── modules/             # 业务模块 M01~M17
│   ├── db/                  # 会话、ORM 基类、模型、Alembic 迁移
│   ├── infra/               # Redis / Milvus / Neo4j / ES / MinIO 客户端
│   ├── tasks/               # Celery 任务（document / schedule）
│   ├── schemas/             # Pydantic 请求响应模型
│   └── utils/               # UUIDv7、排序白名单等工具
├── tests/                   # unit / integration
├── alembic.ini
├── .env.example
└── Dockerfile
```

## 本地开发

开发采用**混合模式**：业务服务跑在本机（热重载），中间件用测试服务器上已部署的实例。
详见 [docs/开发环境说明.md](../docs/开发环境说明.md)。

```bash
# 1. 安装依赖（在项目根目录）
uv sync

# 2. 生成 backend/.env（自动从服务器读取服务凭据）
python scripts/dev/setup_local_env.py

# 3. 检查到中间件的连通性
python scripts/dev/check_remote_services.py

# 4. 启动（二选一）
#    a) 用统一脚本（在项目根目录）
./scripts/dev/dev.sh api              # 或 Windows: .\scripts\dev\dev.ps1 api
#    b) 直接命令
cd backend && uv run uvicorn app.main:app --reload

# 5. 运行测试
uv run pytest
```

访问 `http://127.0.0.1:8000/docs` 查看接口文档。

如果中间件部署在本机，用 `.env.example`（全 `127.0.0.1`）而不是 `.env.example.local`。

## 关键约定

| 项 | 约定 |
|---|---|
| 统一响应 | `{code, message, data}`，见 `app/core/response.py` |
| 业务异常 | 只抛 `BusinessError` 及其子类，**禁止在业务代码抛 `HTTPException`** |
| 主键 | UUIDv7，`app/utils/ids.py::uuid7()` |
| 物理外键 | **禁止**，表间关系由应用层维护（`docs/rules/database-rules.md` §4） |
| Redis | DB 0 业务，DB 1 被 Langfuse 占用，业务代码访问 DB 1 会抛异常 |
| Token | Access 30 分钟存内存，Refresh 7 天存 httpOnly Cookie（评审 §Q1） |

## 数据库迁移

```bash
cd backend
uv run alembic revision --autogenerate -m "描述"
uv run alembic upgrade head
uv run alembic downgrade -1
```

迁移脚本位于 `app/db/migrations/versions/`。
