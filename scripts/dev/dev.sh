#!/usr/bin/env bash
# ============================================
# 本地混合开发启动脚本（Git Bash / WSL / macOS / Linux）
#
# 业务服务本地跑，中间件用 192.168.75.100 上已部署的实例。
#
# 用法：
#   ./scripts/dev/dev.sh api        # 后端 API（reload）
#   ./scripts/dev/dev.sh worker     # Celery worker
#   ./scripts/dev/dev.sh beat       # Celery beat
#   ./scripts/dev/dev.sh c-end      # C 端 Next.js
#   ./scripts/dev/dev.sh b-end      # B 端 Vite
#   ./scripts/dev/dev.sh check      # 检查远程中间件
#   ./scripts/dev/dev.sh status     # 查看哪些服务在跑
#   ./scripts/dev/dev.sh stop       # 关闭全部本地开发服务
#   ./scripts/dev/dev.sh stop api   # 只关闭后端 API
#
# 关闭方式说明：
#   推荐在对应终端按 Ctrl+C（前台运行，日志实时可见）。
#   stop 是兜底：按端口精准识别，只杀占用本项目开发端口的进程。
# ============================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET="${1:-}"
SERVICE="${2:-}"

# 服务名 -> 开发端口
declare -A SERVICE_PORTS=(
    [api]=8000
    [c-end]=3000
    [b-end]=5173
)

require_env() {
    if [[ ! -f "$ROOT/backend/.env" ]]; then
        echo "缺少 backend/.env，请先执行："
        echo "  python scripts/dev/setup_local_env.py"
        exit 1
    fi
}

# 取指定端口的监听进程 PID，可能为空
pids_by_port() {
    local port="$1"
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null || true
    elif command -v ss >/dev/null 2>&1; then
        ss -tlnp 2>/dev/null | awk -v p=":$port" '$4 ~ p {print $NF}' \
            | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true
    fi
}

# 取 Celery 相关进程 PID（无监听端口，按命令行匹配）
celery_pids() {
    local kind="$1"
    pgrep -f "celery.*app.tasks.celery_app.*${kind}" 2>/dev/null || true
}

show_status() {
    echo "本地开发服务状态"
    echo "----------------------------------------------"
    for name in api c-end b-end; do
        local port="${SERVICE_PORTS[$name]}"
        local pids
        pids="$(pids_by_port "$port" | tr '\n' ' ')"
        if [[ -n "${pids// /}" ]]; then
            echo "  $(printf '%-8s' "$name") :$(printf '%-6s' "$port") 运行中  PID ${pids}"
        else
            echo "  $(printf '%-8s' "$name") :$(printf '%-6s' "$port") 未运行"
        fi
    done
    for name in worker beat; do
        local pids
        pids="$(celery_pids "$name" | tr '\n' ' ')"
        if [[ -n "${pids// /}" ]]; then
            echo "  $(printf '%-8s' "$name") $(printf '%-8s' '') 运行中  PID ${pids}"
        else
            echo "  $(printf '%-8s' "$name") $(printf '%-8s' '') 未运行"
        fi
    done
}

stop_services() {
    local only="${1:-}"
    local names=(api c-end b-end worker beat)

    if [[ -n "$only" ]]; then
        local found=0
        for n in "${names[@]}"; do [[ "$n" == "$only" ]] && found=1; done
        if [[ $found -eq 0 ]]; then
            echo "未知服务: $only（可选: ${names[*]}）"
            exit 1
        fi
        names=("$only")
    fi

    local stopped=0
    for name in "${names[@]}"; do
        local pids
        if [[ "$name" == "worker" || "$name" == "beat" ]]; then
            pids="$(celery_pids "$name" | tr '\n' ' ')"
        else
            pids="$(pids_by_port "${SERVICE_PORTS[$name]}" | tr '\n' ' ')"
        fi

        for pid in $pids; do
            [[ -z "$pid" ]] && continue
            # 只关闭 python / node 进程，避免误杀其他程序
            local cmd
            cmd="$(ps -p "$pid" -o comm= 2>/dev/null || true)"
            if [[ "$cmd" != *python* && "$cmd" != *node* ]]; then
                echo "  跳过 PID $pid（$cmd，不是 python/node）"
                continue
            fi
            if kill -TERM "$pid" 2>/dev/null; then
                echo "  已关闭 $name（PID $pid）"
                stopped=$((stopped + 1))
            else
                echo "  关闭 $name（PID $pid）失败"
            fi
        done
    done

    if [[ $stopped -eq 0 ]]; then
        echo "没有需要关闭的服务。"
    else
        echo ""
        echo "完成。提示：在运行服务的终端里按 Ctrl+C 是更规范的关闭方式。"
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
        exec uv run celery -A app.tasks.celery_app.celery_app worker -l info -Q local --pool=solo
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
    status)
        show_status
        ;;
    stop)
        stop_services "$SERVICE"
        ;;
    *)
        echo "用法: $0 {api|worker|beat|c-end|b-end|check|status|stop}"
        echo ""
        echo "  启动服务（前台运行，Ctrl+C 关闭）："
        echo "    api     后端 API（热重载，:8000）"
        echo "    worker  Celery worker（local 队列）"
        echo "    beat    Celery beat 定时调度"
        echo "    c-end   C 端 Next.js（:3000）"
        echo "    b-end   B 端 Vite（:5173）"
        echo ""
        echo "  其他："
        echo "    check   检查远程中间件连通性"
        echo "    status  查看哪些服务在运行"
        echo "    stop    关闭全部本地开发服务（可加服务名只关一个）"
        exit 1
        ;;
esac
