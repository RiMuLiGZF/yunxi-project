<#
.SYNOPSIS
云汐备份监控告警脚本 - 第四阶段生产就绪

.DESCRIPTION
备份系统监控与告警脚本，支持：
- 备份失败告警
- 备份存储空间监控
- 备份过期提醒
- 恢复演练定期提醒
- 告警查询与管理
- 定时检查（配合 Windows 任务计划）

使用方式：
  .\backup-monitor.ps1 -Check            # 执行全面检查
  .\backup-monitor.ps1 -Status           # 查看状态摘要
  .\backup-monitor.ps1 -Alerts           # 查看告警列表
  .\backup-monitor.ps1 -Resolve <id>     # 标记告警已解决
  .\backup-monitor.ps1 -Watch            # 持续监控模式
  .\backup-monitor.ps1 -Auto             # 自动模式（用于定时任务）

.NOTES
第四阶段 - 容灾与恢复验证
#>

param(
    [Parameter(Mandatory=$false, HelpMessage="执行全面监控检查")]
    [switch]$Check = $false,

    [Parameter(Mandatory=$false, HelpMessage="查看状态摘要")]
    [switch]$Status = $false,

    [Parameter(Mandatory=$false, HelpMessage="查看告警列表")]
    [switch]$Alerts = $false,

    [Parameter(Mandatory=$false, HelpMessage="仅显示活跃告警")]
    [switch]$Active = $false,

    [Parameter(Mandatory=$false, HelpMessage="标记告警已解决")]
    [string]$Resolve = "",

    [Parameter(Mandatory=$false, HelpMessage="解决说明")]
    [string]$Note = "",

    [Parameter(Mandatory=$false, HelpMessage="持续监控模式")]
    [switch]$Watch = $false,

    [Parameter(Mandatory=$false, HelpMessage="自动模式（用于定时任务）")]
    [switch]$Auto = $false,

    [Parameter(Mandatory=$false, HelpMessage="检查间隔（秒，仅 Watch 模式）")]
    [int]$Interval = 300,

    [Parameter(Mandatory=$false, HelpMessage="项目根目录路径")]
    [string]$ProjectRoot = ""
)

# ============================================================
# 初始化
# ============================================================

$ErrorActionPreference = "Stop"

# 确定项目根目录
if (-not $ProjectRoot) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $ProjectRoot = Split-Path -Parent $ScriptDir
}

$BackupMonitorDir = Join-Path $ProjectRoot "shared\data\data_layer"
$BackupMonitorPy = Join-Path $BackupMonitorDir "backup_monitor.py"

# ============================================================
# 辅助函数
# ============================================================

function Get-PythonCmd {
    try {
        & python -c "print('ok')" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { return "python" }
    } catch { }
    try {
        & python3 -c "print('ok')" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { return "python3" }
    } catch { }
    return "python"
}

function Write-Header($title) {
    if ($Auto) { return }
    $line = "=" * 60
    Write-Host ""
    Write-Host $line -ForegroundColor Cyan
    Write-Host "  $title" -ForegroundColor Cyan
    Write-Host $line -ForegroundColor Cyan
    Write-Host ""
}

function Write-Success($msg) {
    if ($Auto) {
        Write-Host "[OK] $msg"
    } else {
        Write-Host "[OK] $msg" -ForegroundColor Green
    }
}

function Write-WarningMsg($msg) {
    if ($Auto) {
        Write-Host "[WARN] $msg"
    } else {
        Write-Host "[WARN] $msg" -ForegroundColor Yellow
    }
}

function Write-Failure($msg) {
    if ($Auto) {
        Write-Host "[CRITICAL] $msg"
    } else {
        Write-Host "[CRITICAL] $msg" -ForegroundColor Red
    }
}

function Write-Info($msg) {
    if ($Auto) { return }
    Write-Host "       $msg" -ForegroundColor Gray
}

# ============================================================
# 检查函数
# ============================================================

function Invoke-MonitorCheck {
    <#
    执行全面监控检查
    #>
    if (-not $Auto) {
        Write-Header "备份监控检查"
    }

    $pythonCmd = Get-PythonCmd

    try {
        $output = & $pythonCmd $BackupMonitorPy check --json 2>&1
        if ($LASTEXITCODE -ne 0 -and -not $output) {
            Write-Failure "监控检查执行失败"
            return $false
        }

        $report = $output | ConvertFrom-Json

        if ($Auto) {
            # 自动模式：简洁输出
            $status = if ($report.overall_healthy) { "HEALTHY" } else { "ISSUES" }
            Write-Host "[$status] modules=$($report.healthy_modules)/$($report.total_modules) " +
                        "storage=$($report.storage_usage_percent)% " +
                        "alerts=$($report.alerts.Count)"
        } else {
            # 详细输出
            Write-Host "  检查时间: $([DateTimeOffset]::FromUnixTimeSeconds($report.timestamp).LocalDateTime.ToString('yyyy-MM-dd HH:mm:ss'))"
            Write-Host "  模块总数: $($report.total_modules)"
            Write-Host "  正常模块: $($report.healthy_modules)" -ForegroundColor Green
            Write-Host "  异常模块: $($report.problematic_modules)" -ForegroundColor $(if ($report.problematic_modules -gt 0) { 'Red' } else { 'Gray' })
            Write-Host "  总备份数: $($report.total_backups)"
            Write-Host "  存储使用率: $($report.storage_usage_percent)%"
            Write-Host ""

            if ($report.overall_healthy) {
                Write-Success "所有检查通过，备份系统运行正常"
            } else {
                Write-WarningMsg "发现 $($report.alerts.Count) 个告警:"
                Write-Host ""
                foreach ($alert in $report.alerts) {
                    $levelColor = if ($alert.level -eq "critical") { 'Red' } else { 'Yellow' }
                    $levelText = if ($alert.level -eq "critical") { '严重' } else { '警告' }
                    Write-Host "  [$levelText] $($alert.module_id): $($alert.message)" -ForegroundColor $levelColor
                }
            }
        }

        return $report.overall_healthy
    } catch {
        Write-Failure "监控检查异常: $($_.Exception.Message)"
        return $false
    }
}

function Get-Status {
    <#
    查看状态摘要
    #>
    Write-Header "备份监控状态"

    $pythonCmd = Get-PythonCmd

    try {
        $output = & $pythonCmd $BackupMonitorPy status 2>&1
        Write-Host $output
    } catch {
        Write-Failure "获取状态失败: $($_.Exception.Message)"
    }
}

function Get-Alerts {
    <#
    查看告警列表
    #>
    Write-Header "告警列表"

    $pythonCmd = Get-PythonCmd
    $args = @("alerts")
    if ($Active) { $args += "--active" }

    try {
        $output = & $pythonCmd $BackupMonitorPy @args 2>&1
        Write-Host $output
    } catch {
        Write-Failure "获取告警失败: $($_.Exception.Message)"
    }
}

function Resolve-Alert($alertId, $note) {
    <#
    标记告警已解决
    #>
    Write-Host "正在解决告警: $alertId"

    $pythonCmd = Get-PythonCmd
    $args = @("resolve", $alertId)
    if ($note) { $args += @("--note", $note) }

    try {
        $output = & $pythonCmd $BackupMonitorPy @args 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Success "告警已标记为已解决"
        } else {
            Write-Failure "操作失败: $output"
        }
    } catch {
        Write-Failure "操作异常: $($_.Exception.Message)"
    }
}

function Invoke-Watch {
    <#
    持续监控模式
    #>
    Write-Header "持续监控模式"
    Write-Host "  检查间隔: $Interval 秒"
    Write-Host "  按 Ctrl+C 停止"
    Write-Host ""

    while ($true) {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Write-Host "[$timestamp] 执行检查..."
        Invoke-MonitorCheck
        Write-Host ""
        Start-Sleep -Seconds $Interval
    }
}

# ============================================================
# 主流程
# ============================================================

function Main {
    # 检查 Python 和监控脚本
    if (-not (Test-Path $BackupMonitorPy)) {
        Write-Failure "监控脚本不存在: $BackupMonitorPy"
        exit 1
    }

    if ($Check -or $Auto) {
        $result = Invoke-MonitorCheck
        exit $(if ($result) { 0 } else { 1 })
    }
    elseif ($Status) {
        Get-Status
    }
    elseif ($Alerts) {
        Get-Alerts
    }
    elseif ($Resolve) {
        Resolve-Alert $Resolve $Note
    }
    elseif ($Watch) {
        Invoke-Watch
    }
    else {
        Write-Host "云汐备份监控告警工具"
        Write-Host ""
        Write-Host "用法:"
        Write-Host "  .\backup-monitor.ps1 -Check          # 执行全面检查"
        Write-Host "  .\backup-monitor.ps1 -Status         # 查看状态摘要"
        Write-Host "  .\backup-monitor.ps1 -Alerts         # 查看告警列表"
        Write-Host "  .\backup-monitor.ps1 -Alerts -Active # 仅活跃告警"
        Write-Host "  .\backup-monitor.ps1 -Resolve <id>   # 标记告警已解决"
        Write-Host "  .\backup-monitor.ps1 -Watch          # 持续监控模式"
        Write-Host "  .\backup-monitor.ps1 -Auto           # 自动模式（定时任务用）"
        exit 1
    }
}

Main
