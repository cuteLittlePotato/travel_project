# ============================================
# 本地混合开发启动脚本（Windows PowerShell）
#
# 业务服务本地跑，中间件用 192.168.75.100 上已部署的实例。
#
# 用法：
#   .\scripts\dev\dev.ps1 api        # 后端 API（reload）
#   .\scripts\dev\dev.ps1 worker     # Celery worker
#   .\scripts\dev\dev.ps1 beat       # Celery beat
#   .\scripts\dev\dev.ps1 c-end      # C 端 Next.js
#   .\scripts\dev\dev.ps1 b-end      # B 端 Vite
#   .\scripts\dev\dev.ps1 check      # 检查远程中间件
# ============================================
param([string]$Target = "")

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Root) { $Root = Resolve-Path "$PSScriptRoot\..\.." }

function Require-Env {
    if (-not (Test-Path "$Root\backend\.env")) {
        Write-Host "缺少 backend/.env，请先执行：" -ForegroundColor Yellow
        Write-Host "  python scripts/dev/setup_local_env.py"
        exit 1
    }
}

switch ($Target) {
    "api" {
        Require-Env
        Set-Location "$Root\backend"
        uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    }
    "worker" {
        Require-Env
        Set-Location "$Root\backend"
        uv run celery -A app.tasks.celery_app.celery_app worker -l info -Q default
    }
    "beat" {
        Require-Env
        Set-Location "$Root\backend"
        uv run celery -A app.tasks.celery_app.celery_app beat -l info
    }
    "c-end" {
        Set-Location "$Root\frontend\c-end"
        if (-not (Test-Path "node_modules")) { npm install }
        npm run dev
    }
    "b-end" {
        Set-Location "$Root\frontend\b-end"
        if (-not (Test-Path "node_modules")) { npm install }
        npm run dev
    }
    "check" {
        python "$Root\scripts\dev\check_remote_services.py"
    }
    default {
        Write-Host "用法: .\scripts\dev\dev.ps1 {api|worker|beat|c-end|b-end|check}" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  api     后端 API（热重载，:8000）"
        Write-Host "  worker  Celery worker"
        Write-Host "  beat    Celery beat 定时调度"
        Write-Host "  c-end   C 端 Next.js（:3000）"
        Write-Host "  b-end   B 端 Vite（:5173）"
        Write-Host "  check   检查远程中间件连通性"
        exit 1
    }
}
