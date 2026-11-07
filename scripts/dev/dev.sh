#!/usr/bin/env bash
# ============================================
# 本地混合开发启动脚本
#
# 业务服务本地跑，中间件用 192.168.75.100 上已部署的实例。
# 改代码即时热更新，不用重建镜像、不用上传服务器。
#
# 用法：
#   ./scripts/dev/dev.sh api        # 后端 API（reload）
#   ./scripts/dev/dev.sh worker     # Celery worker
#   ./scripts/dev/dev.sh beat       # Celery beat
#   ./scripts/dev/dev.sh c-end      # C 端 Next.js
#   ./scripts/dev/dev.sh b-end      # B 端 Vite
# ============================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET="${1:-}"

require_env() {
    if [[ ! -f "$ROOT/backend/.env" ]]; then
        echo "缺少 backend/.env，请先执行："
        echo "  python scripts/dev/setup_local_env.py"
        exit 1
    fi
}

case "$TARGET" in
    api)
        require_env
        cd "$ROOT/backend"
        exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
        ;;
    worker)
        require_env
        cd "$ROOT/backend"
        exec uv run celery -A app.tasks.celery_app.celery_app worker -l info -Q default
        ;;
    beat)
        require_env
        cd "$ROOT/backend"
        exec uv run celery -A app.tasks.celery_app.celery_app beat -l info
        ;;
    c-end)
        cd "$ROOT/frontend/c-end"
        [[ -d node_modules ]] || npm install
        exec npm run dev
        ;;
    b-end)
        cd "$ROOT/frontend/b-end"
        [[ -d node_modules ]] || npm install
        exec npm run dev
        ;;
    check)
        exec python "$ROOT/scripts/dev/check_remote_services.py"
        ;;
    *)
        echo "用法: $0 {api|worker|beat|c-end|b-end|check}"
        echo ""
        echo "  api     后端 API（热重载，:8000）"
        echo "  worker  Celery worker"
        echo "  beat    Celery beat 定时调度"
        echo "  c-end   C 端 Next.js（:3000）"
        echo "  b-end   B 端 Vite（:5173）"
        echo "  check   检查远程中间件连通性"
        exit 1
        ;;
esac
