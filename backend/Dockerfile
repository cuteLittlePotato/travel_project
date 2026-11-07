# ============================================
# 云游坊后端镜像
# 构建上下文为项目根目录（需要 pyproject.toml / uv.lock）：
#   docker build -f backend/Dockerfile -t travel-backend .
# ============================================
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_DEFAULT_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"

WORKDIR /app

# 依赖层单独缓存，代码变更不触发重装
COPY pyproject.toml uv.lock .python-version ./
# 通过 --build-arg WHEEL_DIR=/app/.wheels 使用预下载的 wheel 离线安装（弱网环境）
ARG WHEEL_DIR=""
COPY [".wheels", "/app/.wheels"]
RUN if [ -n "$WHEEL_DIR" ]; then \
        uv export --frozen --no-dev --no-hashes --no-emit-project -o /tmp/requirements.txt && \
        uv venv /app/.venv && \
        uv pip install --python /app/.venv/bin/python --no-index \
            --find-links "$WHEEL_DIR" -r /tmp/requirements.txt; \
    else \
        uv sync --frozen --no-dev --no-install-project; \
    fi

# 业务代码直接以源码目录运行，无需安装为包（避免二次联网解析依赖）
COPY backend/ ./backend/


FROM python:3.12-slim-bookworm AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 非 root 运行
RUN groupadd --gid 1000 travel && useradd --uid 1000 --gid travel --create-home travel

WORKDIR /app
COPY --from=builder --chown=travel:travel /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="/app/backend"

WORKDIR /app/backend
USER travel

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
