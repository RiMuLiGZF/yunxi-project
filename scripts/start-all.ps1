<#
.SYNOPSIS
云汐系统一键启动脚本
.DESCRIPTION
按依赖顺序启动所有模块（M0-M12），覆盖全部13个模块
#>

$ErrorActionPreference = "Continue"
$BaseDir = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $BaseDir "logs"

# 确保日志目录存在
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# 模块配置（按启动依赖顺序排列）
$Modules = @(
    @{
        Name = "M5-潮汐记忆"
        Port = 8005
        Path = "M5-tide-memory"
        Cmd = "python src/main.py"
        LogFile = "m5.log"
    },
    @{
        Name = "M2-技能集群"
        Port = 8002
        Path = "M2-skills-cluster"
        Cmd = "python start_server.py"
        LogFile = "m2.log"
    },
    @{
        Name = "M4-场景引擎"
        Port = 8004
        Path = "m4-scene-engine"
        Cmd = "python -m src.main"
        LogFile = "m4.log"
    },
    @{
        Name = "M3-端云协同"
        Port = 8003
        Path = "M3-edge-cloud"
        Cmd = "python server.py"
        LogFile = "m3.log"
    },
    @{
        Name = "M6-硬件外设"
        Port = 8006
        Path = "M6-hardware-peripheral"
        Cmd = "python server.py"
        LogFile = "m6.log"
    },
    @{
        Name = "M1-Agent调度"
        Port = 8001
        Path = "M1-agent-hub"
        Cmd = "python server.py"
        LogFile = "m1.log"
    },
    @{
        Name = "M7-积木编排"
        Port = 8007
        Path = "M7-workflow-builder"
        Cmd = "python -m src.main"
        LogFile = "m7.log"
    },
    @{
        Name = "M8-控制塔"
        Port = 8008
        Path = "M8-control-tower"
        Cmd = "python -m backend.main"
        LogFile = "m8.log"
    },
    @{
        Name = "M9-开发者工坊"
        Port = 8009
        Path = "M9-dev-workshop"
        Cmd = "python backend/main.py"
        LogFile = "m9.log"
    },
    @{
        Name = "M10-系统卫士"
        Port = 8010
        Path = "M10-system-guard"
        Cmd = "python server.py"
        LogFile = "m10.log"
    },
    @{
        Name = "M0-主理人管控台"
        Port = 8000
        Path = "M0-principal-console"
        Cmd = "python -m src.main"
        LogFile = "m0.log"
    },
    @{
        Name = "M11-MCP总线"
        Port = 8011
        Path = "M11-mcp-bus"
        Cmd = "python -m src.main"
        LogFile = "m11.log"
    },
    @{
        Name = "M12-安全盾"
        Port = 8012
        Path = "M12-security-shield"
        Cmd = 'python -m backend.main'
        LogFile = "m12.log"
    }
)

$Processes = @()

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  🌊  云汐系统启动中..." -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

$successCount = 0
$failCount = 0

foreach ($mod in $Modules) {
    $modPath = Join-Path $BaseDir $mod.Path
    $logPath = Join-Path $LogDir $mod.LogFile

    if (-not (Test-Path $modPath)) {
        Write-Host "  [跳过] $($mod.Name) - 目录不存在" -ForegroundColor Yellow
        continue
    }

    Write-Host "  [启动] $($mod.Name) (端口 $($mod.Port))..." -ForegroundColor Green

    try {
        $process = Start-Process -FilePath "powershell" `
            -ArgumentList "-NoExit", "-Command", "cd '$modPath'; $($mod.Cmd) 2>&1 | Tee-Object -FilePath '$logPath'" `
            -PassThru -WindowStyle Normal

        $Processes += @{ Name = $mod.Name; Process = $process; Port = $mod.Port }

        # 等待端口就绪（最多20秒）
        $timeout = 20
        $elapsed = 0
        $ready = $false
        while ($elapsed -lt $timeout) {
            try {
                $tcp = New-Object System.Net.Sockets.TcpClient
                $tcp.Connect("127.0.0.1", $mod.Port)
                $tcp.Close()
                $ready = $true
                break
            } catch {
                Start-Sleep -Milliseconds 500
                $elapsed += 0.5
            }
        }

        if ($ready) {
            Write-Host "  [就绪] $($mod.Name) 启动成功 ✓" -ForegroundColor Green
            $successCount++
        } else {
            Write-Host "  [超时] $($mod.Name) 启动超时，请检查日志: $logPath" -ForegroundColor Yellow
            $failCount++
        }
    } catch {
        Write-Host "  [失败] $($mod.Name) 启动失败: $($_.Exception.Message)" -ForegroundColor Red
        $failCount++
    }
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  启动完成！成功 $successCount / $($Modules.Count)" -ForegroundColor $(if ($failCount -eq 0) { "Green" } else { "Yellow" })
Write-Host "  M0 主理人管控台: http://localhost:8000" -ForegroundColor White
Write-Host "  M8 控制塔: http://localhost:8008" -ForegroundColor White
Write-Host "  M9 开发者工坊: http://localhost:8009" -ForegroundColor White
Write-Host "  M11 MCP总线: http://localhost:8011" -ForegroundColor White
Write-Host "  M12 安全盾: http://localhost:8012" -ForegroundColor White
Write-Host "  日志目录: $LogDir" -ForegroundColor Gray
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  按 Ctrl+C 停止所有模块并退出" -ForegroundColor Gray
Write-Host ""

# 保持脚本运行
try {
    while ($true) { Start-Sleep -Seconds 5 }
} finally {
    Write-Host ""
    Write-Host "  正在停止所有模块..." -ForegroundColor Yellow
    foreach ($p in $Processes) {
        if (-not $p.Process.HasExited) {
            try {
                Stop-Process -Id $p.Process.Id -Force -ErrorAction SilentlyContinue
                Write-Host "  [停止] $($p.Name)" -ForegroundColor Red
            } catch { }
        }
    }
    Write-Host ""
    Write-Host "  所有模块已停止" -ForegroundColor Green
    Write-Host ""
}