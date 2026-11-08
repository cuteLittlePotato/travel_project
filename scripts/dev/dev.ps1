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
#   .\scripts\dev\dev.ps1 status     # 查看哪些服务在跑
#   .\scripts\dev\dev.ps1 stop       # 关闭全部本地开发服务
#   .\scripts\dev\dev.ps1 stop api   # 只关闭后端 API
#
# 关闭方式说明：
#   推荐在对应终端按 Ctrl+C（前台运行，日志实时可见）。
#   stop 是「忘记关、进程残留」时的兜底：按端口精准识别，
#   只杀占用本项目开发端口的进程，不影响 IDE 或其他项目。
# ============================================
param(
    [string]$Target = "",
    [string]$Service = ""
)

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Root) { $Root = Resolve-Path "$PSScriptRoot\..\.." }

# 服务名 -> 开发端口。stop/status 依据端口识别进程，避免误杀。
$ServicePorts = [ordered]@{
    "api"    = 8000
    "c-end"  = 3000
    "b-end"  = 5173
}

function Require-Env {
    if (-not (Test-Path "$Root\backend\.env")) {
        Write-Host "缺少 backend/.env，请先执行：" -ForegroundColor Yellow
        Write-Host "  python scripts/dev/setup_local_env.py"
        exit 1
    }
}

# 返回占用指定端口的 PID 列表（可能为空）
function Get-PidsByPort([int]$Port) {
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if (-not $conns) { return @() }
        return @($conns | Select-Object -ExpandProperty OwningProcess -Unique |
                 Where-Object { $_ -ne 0 })
    } catch {
        return @()
    }
}

# 返回指定服务的 PID 列表
function Get-ServicePids([string]$Name) {
    if ($Name -eq "worker" -or $Name -eq "beat") {
        # Celery 没有监听端口，按命令行关键字识别本项目进程
        try {
            return @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
                     Where-Object { $_.CommandLine -like "*celery*app.tasks.celery_app*$Name*" } |
                     Select-Object -ExpandProperty ProcessId)
        } catch {
            return @()
        }
    }

    $port = $ServicePorts[$Name]
    if (-not $port) { return @() }
    return Get-PidsByPort $port
}

# 进程所属的进程名，用于提示
function Get-ProcessName([int]$ProcId) {
    try {
        return (Get-Process -Id $ProcId -ErrorAction Stop).ProcessName
    } catch {
        return "unknown"
    }
}

# 是否为本项目可识别的开发进程（python / node）
function Test-DevProcess([int]$ProcId) {
    $name = Get-ProcessName $ProcId
    return ($name -in @("python", "python3", "node"))
}

function Show-Status {
    Write-Host "本地开发服务状态" -ForegroundColor Cyan
    Write-Host ("-" * 46)

    foreach ($name in $ServicePorts.Keys) {
        $port = $ServicePorts[$name]
        $pids = Get-PidsByPort $port
        if ($pids.Count -gt 0) {
            $detail = ($pids | ForEach-Object { "$_( $((Get-ProcessName $_)))" }) -join ", "
            Write-Host ("  {0,-8} :{1,-6} 运行中  PID {2}" -f $name, $port, $detail) -ForegroundColor Green
        } else {
            Write-Host ("  {0,-8} :{1,-6} 未运行" -f $name, $port) -ForegroundColor DarkGray
        }
    }

    foreach ($name in @("worker", "beat")) {
        $pids = Get-ServicePids $name
        if ($pids.Count -gt 0) {
            Write-Host ("  {0,-8} {1,-8} 运行中  PID {2}" -f $name, "", ($pids -join ", ")) -ForegroundColor Green
        } else {
            Write-Host ("  {0,-8} {1,-8} 未运行" -f $name, "") -ForegroundColor DarkGray
        }
    }
}

function Stop-Services([string]$Only = "") {
    $names = @($ServicePorts.Keys) + @("worker", "beat")
    if ($Only) {
        if ($names -notcontains $Only) {
            Write-Host "未知服务: $Only（可选: $($names -join ', ')）" -ForegroundColor Red
            exit 1
        }
        $names = @($Only)
    }

    $stopped = 0
    foreach ($name in $names) {
        $pids = Get-ServicePids $name
        if ($pids.Count -eq 0) { continue }

        foreach ($procId in $pids) {
            if (-not (Test-DevProcess $procId)) {
                Write-Host ("  跳过 PID {0}（{1}，不是 python/node）" -f $procId, (Get-ProcessName $procId)) -ForegroundColor Yellow
                continue
            }
            try {
                # 只杀进程树中的该进程；uvicorn --reload 会派生子进程，需连子进程一起结束
                $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $procId" -ErrorAction SilentlyContinue |
                              Select-Object -ExpandProperty ProcessId)
                foreach ($child in $children) {
                    Stop-Process -Id $child -Force -ErrorAction SilentlyContinue
                }
                Stop-Process -Id $procId -Force -ErrorAction Stop
                Write-Host ("  已关闭 {0}（PID {1}）" -f $name, $procId) -ForegroundColor Green
                $stopped++
            } catch {
                Write-Host ("  关闭 {0}（PID {1}）失败: {2}" -f $name, $procId, $_.Exception.Message) -ForegroundColor Red
            }
        }
    }

    if ($stopped -eq 0) {
        Write-Host "没有需要关闭的服务。" -ForegroundColor DarkGray
    } else {
        Write-Host ""
        Write-Host "完成。提示：在运行服务的终端里按 Ctrl+C 是更规范的关闭方式。" -ForegroundColor DarkGray
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
        uv run celery -A app.tasks.celery_app.celery_app worker -l info -Q local --pool=solo
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
    "status" {
        Show-Status
    }
    "stop" {
        Stop-Services $Service
    }
    default {
        Write-Host "用法: .\scripts\dev\dev.ps1 {api|worker|beat|c-end|b-end|check|status|stop}" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  启动服务（前台运行，Ctrl+C 关闭）："
        Write-Host "    api     后端 API（热重载，:8000）"
        Write-Host "    worker  Celery worker（local 队列）"
        Write-Host "    beat    Celery beat 定时调度"
        Write-Host "    c-end   C 端 Next.js（:3000）"
        Write-Host "    b-end   B 端 Vite（:5173）"
        Write-Host ""
        Write-Host "  其他："
        Write-Host "    check   检查远程中间件连通性"
        Write-Host "    status  查看哪些服务在运行"
        Write-Host "    stop    关闭全部本地开发服务（可加服务名只关一个）"
        exit 1
    }
}
