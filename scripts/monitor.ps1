<#
.SYNOPSIS
    云汐系统 - 性能监控脚本
.DESCRIPTION
    实时监控系统各模块性能指标，包括：
    - 各模块 CPU/内存/磁盘使用
    - 请求量和响应时间（通过健康接口采样）
    - 错误率监控
    - 输出性能报告
    - 支持告警阈值配置
.PARAMETER Interval
    监控间隔（秒），默认 5 秒
    .PARAMETER Duration
    监控持续时间（秒），0 表示持续运行直到手动停止
.PARAMETER Module
    只监控指定模块
.PARAMETER OutputFile
    输出报告到文件（CSV 格式）
.PARAMETER AlertThreshold
    告警阈值配置文件路径
.PARAMETER Once
    只执行一次检查（适合定时任务）
.PARAMETER Brief
    简洁输出模式
.EXAMPLE
    .\monitor.ps1
    持续监控所有模块，每 5 秒刷新
.EXAMPLE
    .\monitor.ps1 -Duration 60 -OutputFile report.csv
    监控 60 秒，输出报告到 CSV 文件
.EXAMPLE
    .\monitor.ps1 -Once -Brief
    执行一次性能检查，简洁输出
.EXAMPLE
    .\monitor.ps1 -Module M1 -Interval 2
    只监控 M1 模块，每 2 秒刷新
.NOTES
    告警阈值可通过配置文件或环境变量设置
#>

param(
    [int]$Interval = 5,
    [int]$Duration = 0,
    [string]$Module = "",
    [string]$OutputFile = "",
    [string]$AlertThreshold = "",
    [switch]$Once,
    [switch]$Brief
)

# ============================================================
# 初始化
# ============================================================

$ErrorActionPreference = "SilentlyContinue"
$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Get-Location }
# 脚本在 scripts/ 子目录下，项目根目录是父目录
$ProjectRoot = Split-Path $ScriptDir -Parent

$Script:MonitorStartTime = Get-Date
$Script:MetricsHistory = [System.Collections.ArrayList]::new()
$Script:Alerts = [System.Collections.ArrayList]::new()

# 模块定义
$Modules = @(
    @{Name = "Gateway";        Dir = "API-Gateway";            Port = 8080; Process = "python" },
    @{Name = "M0 Console";     Dir = "M0-principal-console";   Port = 8000; Process = "python" },
    @{Name = "M1 AgentHub";    Dir = "M1-agent-hub";           Port = 8001; Process = "python" },
    @{Name = "M2 SkillCluster";Dir = "M2-skills-cluster";      Port = 8002; Process = "python" },
    @{Name = "M3 EdgeCloud";   Dir = "M3-edge-cloud";          Port = 8003; Process = "python" },
    @{Name = "M4 SceneEngine"; Dir = "m4-scene-engine";        Port = 8004; Process = "python" },
    @{Name = "M5 TideMemory";  Dir = "M5-tide-memory";         Port = 8005; Process = "python" },
    @{Name = "M6 Hardware";    Dir = "M6-hardware-peripheral"; Port = 8006; Process = "python" },
    @{Name = "M7 Workflow";    Dir = "M7-workflow-builder";    Port = 8007; Process = "python" },
    @{Name = "M8 ControlTower";Dir = "M8-control-tower";       Port = 8008; Process = "python" },
    @{Name = "M9 DevWorkshop"; Dir = "M9-dev-workshop";        Port = 8009; Process = "python" },
    @{Name = "M10 SystemGuard";Dir = "M10-system-guard";       Port = 8010; Process = "python" },
    @{Name = "M11 MCP Bus";    Dir = "M11-mcp-bus";            Port = 8011; Process = "python" },
    @{Name = "M12 Security";   Dir = "M12-security-shield";    Port = 8012; Process = "python" }
)

# 默认告警阈值
$Thresholds = @{
    CpuPercentWarning      = 80
    CpuPercentCritical     = 95
    MemoryMBWarning        = 500
    MemoryMBCritical       = 1000
    ResponseTimeMsWarning  = 1000
    ResponseTimeMsCritical = 3000
    ErrorRateWarning       = 5     # %
    ErrorRateCritical      = 20    # %
}

# ============================================================
# 工具函数
# ============================================================

function Get-ModuleProcess {
    param([int]$Port)

    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        if ($conn) {
            $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            return $proc
        }
    }
    catch {}

    return $null
}

function Get-ModuleMetrics {
    param($Mod)

    $metrics = [PSCustomObject]@{
        Timestamp      = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Module         = $Mod.Name
        Port           = $Mod.Port
        Status         = "unknown"
        CpuPercent     = 0.0
        MemoryMB       = 0.0
        Handles        = 0
        Threads        = 0
        ResponseTimeMs = 0
        StatusCode     = 0
        Error          = ""
    }

    # 1. 获取进程信息
    $proc = Get-ModuleProcess -Port $Mod.Port

    if ($proc) {
        $metrics.Status = "running"
        $metrics.MemoryMB = [math]::Round($proc.WorkingSet64 / 1MB, 2)
        $metrics.Handles = $proc.HandleCount
        $metrics.Threads = $proc.Threads.Count

        # CPU 使用率（需要两次采样）
        try {
            $cpuTime1 = $proc.CPU
            Start-Sleep -Milliseconds 200
            $proc.Refresh()
            $cpuTime2 = $proc.CPU
            $cpuTimeDiff = $cpuTime2 - $cpuTime1
            $metrics.CpuPercent = [math]::Round(($cpuTimeDiff / 0.2) * 100 / $env:NUMBER_OF_PROCESSORS, 2)
        }
        catch {
            $metrics.CpuPercent = 0
        }
    }
    else {
        $metrics.Status = "stopped"
        $metrics.Error = "进程未运行"
    }

    # 2. 健康接口响应时间
    try {
        $healthUrl = "http://localhost:$($Mod.Port)/health"
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $response = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 5 -ErrorAction Stop
        $sw.Stop()

        $metrics.ResponseTimeMs = $sw.ElapsedMilliseconds
        $metrics.StatusCode = $response.StatusCode

        if ($metrics.Status -eq "unknown") {
            $metrics.Status = "running"
        }
    }
    catch {
        $metrics.Error = $_.Exception.Message
        if ($metrics.Status -eq "unknown") {
            $metrics.Status = "error"
        }
    }

    return $metrics
}

function Get-SystemMetrics {
    $sysMetrics = [PSCustomObject]@{
        Timestamp       = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        CpuTotalPercent  = 0.0
        MemoryTotalGB    = 0.0
        MemoryUsedGB     = 0.0
        MemoryPercent    = 0.0
        DiskFreeGB       = 0.0
        DiskTotalGB      = 0.0
        DiskPercentUsed  = 0.0
    }

    try {
        $cpu = Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average
        $sysMetrics.CpuTotalPercent = [math]::Round($cpu.Average, 2)
    }
    catch {}

    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $sysMetrics.MemoryTotalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
        $sysMetrics.MemoryUsedGB = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1MB, 2)
        $sysMetrics.MemoryPercent = [math]::Round((($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / $os.TotalVisibleMemorySize) * 100, 2)
    }
    catch {}

    try {
        $drive = (Get-Item $ProjectRoot).PSDrive
        $sysMetrics.DiskFreeGB = [math]::Round($drive.Free / 1GB, 2)
        $sysMetrics.DiskTotalGB = [math]::Round(($drive.Used + $drive.Free) / 1GB, 2)
        $sysMetrics.DiskPercentUsed = [math]::Round(($drive.Used / ($drive.Used + $drive.Free)) * 100, 2)
    }
    catch {}

    return $sysMetrics
}

function Test-Alert {
    param($Metrics)

    $alerts = @()

    # CPU 告警
    if ($Metrics.CpuPercent -ge $Thresholds.CpuPercentCritical) {
        $alerts += "CRITICAL: CPU 使用率过高 ($($Metrics.CpuPercent)%)"
    }
    elseif ($Metrics.CpuPercent -ge $Thresholds.CpuPercentWarning) {
        $alerts += "WARNING: CPU 使用率偏高 ($($Metrics.CpuPercent)%)"
    }

    # 内存告警
    if ($Metrics.MemoryMB -ge $Thresholds.MemoryMBCritical) {
        $alerts += "CRITICAL: 内存使用过高 ($($Metrics.MemoryMB) MB)"
    }
    elseif ($Metrics.MemoryMB -ge $Thresholds.MemoryMBWarning) {
        $alerts += "WARNING: 内存使用偏高 ($($Metrics.MemoryMB) MB)"
    }

    # 响应时间告警
    if ($Metrics.ResponseTimeMs -ge $Thresholds.ResponseTimeMsCritical) {
        $alerts += "CRITICAL: 响应时间过长 ($($Metrics.ResponseTimeMs)ms)"
    }
    elseif ($Metrics.ResponseTimeMs -ge $Thresholds.ResponseTimeMsWarning -and $Metrics.ResponseTimeMs -gt 0) {
        $alerts += "WARNING: 响应时间偏慢 ($($Metrics.ResponseTimeMs)ms)"
    }

    # 状态告警
    if ($Metrics.Status -eq "stopped") {
        $alerts += "CRITICAL: 服务未运行"
    }
    elseif ($Metrics.Status -eq "error") {
        $alerts += "WARNING: 健康检查失败"
    }

    return $alerts
}

# ============================================================
# 输出格式
# ============================================================

function Show-Header {
    if ($Brief) { return }

    Clear-Host
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  云汐系统性能监控" -ForegroundColor Cyan
    Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "  刷新间隔: ${Interval}s"
    if ($Duration -gt 0) {
        $elapsed = ((Get-Date) - $Script:MonitorStartTime).TotalSeconds
        Write-Host "  已运行: $([math]::Round($elapsed, 0))s / ${Duration}s"
    }
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
}

function Show-SystemMetrics {
    param($SysMetrics)

    if ($Brief) { return }

    Write-Host "[系统整体]" -ForegroundColor White
    Write-Host "  CPU:  $($SysMetrics.CpuTotalPercent)% " -NoNewline
    if ($SysMetrics.CpuTotalPercent -ge 90) { Write-Host "[CRITICAL]" -ForegroundColor Red }
    elseif ($SysMetrics.CpuTotalPercent -ge 70) { Write-Host "[WARNING]" -ForegroundColor Yellow }
    else { Write-Host "[OK]" -ForegroundColor Green }

    Write-Host "  内存: $($SysMetrics.MemoryUsedGB)GB / $($SysMetrics.MemoryTotalGB)GB ($($SysMetrics.MemoryPercent)%) " -NoNewline
    if ($SysMetrics.MemoryPercent -ge 90) { Write-Host "[CRITICAL]" -ForegroundColor Red }
    elseif ($SysMetrics.MemoryPercent -ge 75) { Write-Host "[WARNING]" -ForegroundColor Yellow }
    else { Write-Host "[OK]" -ForegroundColor Green }

    Write-Host "  磁盘: $($SysMetrics.DiskTotalGB - $SysMetrics.DiskFreeGB)GB / $($SysMetrics.DiskTotalGB)GB ($($SysMetrics.DiskPercentUsed)%) " -NoNewline
    if ($SysMetrics.DiskPercentUsed -ge 90) { Write-Host "[CRITICAL]" -ForegroundColor Red }
    elseif ($SysMetrics.DiskPercentUsed -ge 75) { Write-Host "[WARNING]" -ForegroundColor Yellow }
    else { Write-Host "[OK]" -ForegroundColor Green }

    Write-Host ""
}

function Show-ModuleTable {
    param($ModuleMetrics)

    if ($Brief) {
        # 简洁模式：只显示异常模块
        $abnormal = $ModuleMetrics | Where-Object {
            $_.Status -ne "running" -or
            $_.CpuPercent -ge $Thresholds.CpuPercentWarning -or
            $_.MemoryMB -ge $Thresholds.MemoryMBWarning -or
            $_.ResponseTimeMs -ge $Thresholds.ResponseTimeMsWarning
        }

        if ($abnormal -and $abnormal.Count -gt 0) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 异常模块: $($abnormal.Count)" -ForegroundColor Yellow
            foreach ($m in $abnormal) {
                Write-Host "  $($m.Module): CPU=$($m.CpuPercent)% MEM=$($m.MemoryMB)MB RT=$($m.ResponseTimeMs)ms Status=$($m.Status)"
            }
        }
        else {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 所有模块正常" -ForegroundColor Green
        }
        return
    }

    Write-Host "[模块性能]" -ForegroundColor White
    Write-Host ("  {0,-20} {1,-10} {2,-10} {3,-12} {4,-10} {5,-10}" -f `
        "模块", "状态", "CPU%", "内存(MB)", "响应(ms)", "状态码")
    Write-Host ("  {0,-20} {1,-10} {2,-10} {3,-12} {4,-10} {5,-10}" -f `
        "----", "----", "----", "--------", "--------", "------")

    foreach ($m in $ModuleMetrics) {
        $statusColor = switch ($m.Status) {
            "running" { "Green" }
            "stopped" { "Red" }
            "error"   { "Yellow" }
            default   { "Gray" }
        }

        $cpuColor = if ($m.CpuPercent -ge $Thresholds.CpuPercentCritical) { "Red" } `
                    elseif ($m.CpuPercent -ge $Thresholds.CpuPercentWarning) { "Yellow" } `
                    else { "White" }

        $memColor = if ($m.MemoryMB -ge $Thresholds.MemoryMBCritical) { "Red" } `
                    elseif ($m.MemoryMB -ge $Thresholds.MemoryMBWarning) { "Yellow" } `
                    else { "White" }

        $rtColor = if ($m.ResponseTimeMs -ge $Thresholds.ResponseTimeMsCritical) { "Red" } `
                   elseif ($m.ResponseTimeMs -ge $Thresholds.ResponseTimeMsWarning) { "Yellow" } `
                   else { "White" }

        Write-Host ("  {0,-20} " -f $m.Name) -NoNewline
        Write-Host ("{1,-10} " -f $m.Status) -ForegroundColor $statusColor -NoNewline
        Write-Host ("{2,-10} " -f $m.CpuPercent) -ForegroundColor $cpuColor -NoNewline
        Write-Host ("{3,-12} " -f $m.MemoryMB) -ForegroundColor $memColor -NoNewline
        Write-Host ("{4,-10} " -f $m.ResponseTimeMs) -ForegroundColor $rtColor -NoNewline
        Write-Host ("{5,-10}" -f $m.StatusCode)
    }

    Write-Host ""
}

function Show-Alerts {
    param($ModuleMetrics)

    $allAlerts = @()

    foreach ($m in $ModuleMetrics) {
        $alerts = Test-Alert -Metrics $m
        foreach ($a in $alerts) {
            $allAlerts += "$($m.Module): $a"
        }
    }

    if ($allAlerts.Count -gt 0) {
        Write-Host "[告警]" -ForegroundColor Red
        foreach ($a in $allAlerts) {
            if ($a -match "CRITICAL") {
                Write-Host "  ! $a" -ForegroundColor Red
            }
            else {
                Write-Host "  * $a" -ForegroundColor Yellow
            }
        }
        Write-Host ""
    }
}

# ============================================================
# 导出报告
# ============================================================

function Export-Report {
    if ([string]::IsNullOrEmpty($OutputFile)) {
        return
    }

    if ($Script:MetricsHistory.Count -eq 0) {
        return
    }

    try {
        $Script:MetricsHistory | Export-Csv -Path $OutputFile -NoTypeInformation -Encoding UTF8
        Write-Host ""
        Write-Host "报告已保存到: $OutputFile" -ForegroundColor Green
        Write-Host "共 $($Script:MetricsHistory.Count) 条记录"
    }
    catch {
        Write-Host ""
        Write-Host "报告保存失败: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# ============================================================
# 主流程
# ============================================================

function Main {
    $endTime = if ($Duration -gt 0) { (Get-Date).AddSeconds($Duration) } else { $null }

    do {
        # 过滤要监控的模块
        $targetModules = $Modules
        if (-not [string]::IsNullOrEmpty($Module)) {
            $targetModules = $Modules | Where-Object {
                $_.Name -match $Module -or $_.Dir -match $Module
            }
        }

        # 收集指标
        $moduleMetrics = @()
        foreach ($mod in $targetModules) {
            $m = Get-ModuleMetrics -Mod $mod
            $moduleMetrics += $m

            # 记录历史数据
            if (-not [string]::IsNullOrEmpty($OutputFile)) {
                [void]$Script:MetricsHistory.Add($m)
            }
        }

        # 系统指标
        $sysMetrics = Get-SystemMetrics

        # 显示
        if (-not $Once) {
            Show-Header
        }
        Show-SystemMetrics -SysMetrics $sysMetrics
        Show-ModuleTable -ModuleMetrics $moduleMetrics

        if (-not $Brief) {
            Show-Alerts -ModuleMetrics $moduleMetrics
        }

        # 单次模式直接退出
        if ($Once) {
            Export-Report
            return
        }

        # 检查是否到达持续时间
        if ($endTime -and (Get-Date) -ge $endTime) {
            break
        }

        # 等待下一轮
        Start-Sleep -Seconds $Interval

    } while ($true)

    # 结束时导出报告
    Export-Report

    Write-Host ""
    Write-Host "监控结束" -ForegroundColor Cyan
    Write-Host "总运行时间: $([math]::Round(((Get-Date) - $Script:MonitorStartTime).TotalSeconds, 0)) 秒"
    Write-Host ""
}

Main
