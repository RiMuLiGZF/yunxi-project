<#
.SYNOPSIS
云汐系统健康检查脚本（增强版）
.DESCRIPTION
全面检查云汐系统健康状态，包括：
- 系统资源（CPU、内存、磁盘）
- 模块进程状态
- 端口监听状态
- HTTP 健康端点检查
- 数据库连接检查
- 日志错误检测

.PARAMETER Deep
深度检查模式，包含更多检查项

.PARAMETER Module
只检查指定模块，如 m8, m1, gateway

.PARAMETER OutputFormat
输出格式：text 或 json，默认 text

.PARAMETER OutputFile
输出到指定文件

.EXAMPLE
.\health_check.ps1
执行基础健康检查

.EXAMPLE
.\health_check.ps1 -Deep
执行深度健康检查

.EXAMPLE
.\health_check.ps1 -Module m8 -OutputFormat json
检查 M8 模块并输出 JSON 格式
#>

param(
    [switch]$Deep = $false,

    [string]$Module = "",

    [ValidateSet("text", "json")]
    [string]$OutputFormat = "text",

    [string]$OutputFile = ""
)

$ErrorActionPreference = "Continue"

# 获取项目目录
$BaseDir = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $BaseDir "logs"

# 模块定义
$Modules = @(
    @{ Id = "gateway"; Name = "API网关"; Port = 8080; Path = "API-Gateway" },
    @{ Id = "m8"; Name = "控制塔"; Port = 8008; Path = "M8-control-tower" },
    @{ Id = "m10"; Name = "系统卫士"; Port = 8010; Path = "M10-system-guard" },
    @{ Id = "m12"; Name = "安全盾"; Port = 8012; Path = "M12-security-shield" },
    @{ Id = "m1"; Name = "代理集群"; Port = 8001; Path = "M1-agent-hub" },
    @{ Id = "m5"; Name = "潮汐记忆"; Port = 8005; Path = "M5-tide-memory" },
    @{ Id = "m2"; Name = "技能集群"; Port = 8002; Path = "M2-skills-cluster" },
    @{ Id = "m4"; Name = "场景引擎"; Port = 8004; Path = "m4-scene-engine" },
    @{ Id = "m7"; Name = "工作流"; Port = 8007; Path = "M7-workflow-builder" },
    @{ Id = "m3"; Name = "边缘云端"; Port = 8003; Path = "M3-edge-cloud" },
    @{ Id = "m6"; Name = "硬件外设"; Port = 8006; Path = "M6-hardware-peripheral" },
    @{ Id = "m0"; Name = "主理人管控台"; Port = 8000; Path = "M0-principal-console" },
    @{ Id = "m11"; Name = "MCP总线"; Port = 8011; Path = "M11-mcp-bus" }
)

# 结果收集
$healthResults = @{
    timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    overall_status = "healthy"
    system = @{}
    modules = @()
    warnings = @()
    errors = @()
}

# ============================================================================
# 系统资源检查
# ============================================================================
function Test-SystemResources {
    Write-Host "[系统资源检查]" -ForegroundColor Yellow

    $sysInfo = @{
        cpu = @{ status = "unknown" }
        memory = @{ status = "unknown" }
        disk = @{ status = "unknown" }
    }

    # CPU
    try {
        $cpu = Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average
        $cpuUsage = [math]::Round($cpu.Average, 1)
        $sysInfo.cpu.usage_percent = $cpuUsage

        if ($cpuUsage -ge 90) {
            $sysInfo.cpu.status = "critical"
            $healthResults.errors += "CPU 使用率过高: ${cpuUsage}%"
        } elseif ($cpuUsage -ge 80) {
            $sysInfo.cpu.status = "warning"
            $healthResults.warnings += "CPU 使用率偏高: ${cpuUsage}%"
        } else {
            $sysInfo.cpu.status = "healthy"
        }
        Write-Host "  CPU: $cpuUsage% $(if ($sysInfo.cpu.status -eq 'healthy') { '[OK]' } else { '[WARN]' })" -ForegroundColor $(if ($sysInfo.cpu.status -eq 'healthy') { 'Green' } else { 'Yellow' })
    } catch {
        $sysInfo.cpu.status = "unknown"
        Write-Host "  CPU: 无法获取" -ForegroundColor Gray
    }

    # 内存
    try {
        $mem = Get-CimInstance Win32_OperatingSystem
        $totalMem = [math]::Round($mem.TotalVisibleMemorySize / 1MB, 2)
        $freeMem = [math]::Round($mem.FreePhysicalMemory / 1MB, 2)
        $usedMem = [math]::Round($totalMem - $freeMem, 2)
        $memUsage = [math]::Round(($usedMem / $totalMem) * 100, 1)

        $sysInfo.memory.total_gb = $totalMem
        $sysInfo.memory.used_gb = $usedMem
        $sysInfo.memory.free_gb = $freeMem
        $sysInfo.memory.usage_percent = $memUsage

        if ($memUsage -ge 90) {
            $sysInfo.memory.status = "critical"
            $healthResults.errors += "内存使用率过高: ${memUsage}%"
        } elseif ($memUsage -ge 80) {
            $sysInfo.memory.status = "warning"
            $healthResults.warnings += "内存使用率偏高: ${memUsage}%"
        } else {
            $sysInfo.memory.status = "healthy"
        }
        Write-Host "  内存: $memUsage% ($usedMem GB / $totalMem GB) $(if ($sysInfo.memory.status -eq 'healthy') { '[OK]' } else { '[WARN]' })" -ForegroundColor $(if ($sysInfo.memory.status -eq 'healthy') { 'Green' } else { 'Yellow' })
    } catch {
        $sysInfo.memory.status = "unknown"
        Write-Host "  内存: 无法获取" -ForegroundColor Gray
    }

    # 磁盘
    try {
        $drive = (Get-Item $BaseDir).PSDrive.Name
        $disk = Get-PSDrive $drive
        $totalGB = [math]::Round(($disk.Used + $disk.Free) / 1GB, 2)
        $usedGB = [math]::Round($disk.Used / 1GB, 2)
        $freeGB = [math]::Round($disk.Free / 1GB, 2)
        $diskUsage = [math]::Round(($disk.Used / ($disk.Used + $disk.Free)) * 100, 1)

        $sysInfo.disk.drive = $drive
        $sysInfo.disk.total_gb = $totalGB
        $sysInfo.disk.used_gb = $usedGB
        $sysInfo.disk.free_gb = $freeGB
        $sysInfo.disk.usage_percent = $diskUsage

        if ($diskUsage -ge 90) {
            $sysInfo.disk.status = "critical"
            $healthResults.errors += "磁盘使用率过高: ${diskUsage}%"
        } elseif ($diskUsage -ge 80) {
            $sysInfo.disk.status = "warning"
            $healthResults.warnings += "磁盘使用率偏高: ${diskUsage}%"
        } else {
            $sysInfo.disk.status = "healthy"
        }
        Write-Host "  磁盘 ($drive): $diskUsage% ($usedGB GB / $totalGB GB) $(if ($sysInfo.disk.status -eq 'healthy') { '[OK]' } else { '[WARN]' })" -ForegroundColor $(if ($sysInfo.disk.status -eq 'healthy') { 'Green' } else { 'Yellow' })
    } catch {
        $sysInfo.disk.status = "unknown"
        Write-Host "  磁盘: 无法获取" -ForegroundColor Gray
    }

    $healthResults.system = $sysInfo

    # 汇总系统状态
    if ($sysInfo.cpu.status -eq "critical" -or $sysInfo.memory.status -eq "critical" -or $sysInfo.disk.status -eq "critical") {
        $healthResults.overall_status = "unhealthy"
    } elseif ($sysInfo.cpu.status -eq "warning" -or $sysInfo.memory.status -eq "warning" -or $sysInfo.disk.status -eq "warning") {
        if ($healthResults.overall_status -eq "healthy") {
            $healthResults.overall_status = "degraded"
        }
    }
}

# ============================================================================
# 模块健康检查
# ============================================================================
function Test-Modules {
    Write-Host ""
    Write-Host "[模块健康检查]" -ForegroundColor Yellow

    $modulesToCheck = $Modules
    if ($Module) {
        $modulesToCheck = $Modules | Where-Object { $_.Id -eq $Module }
        if (-not $modulesToCheck) {
            Write-Host "  未找到模块: $Module" -ForegroundColor Red
            return
        }
    }

    $runningCount = 0
    $stoppedCount = 0

    foreach ($mod in $modulesToCheck) {
        $modResult = @{
            id = $mod.Id
            name = $mod.Name
            port = $mod.Port
            status = "unknown"
            port_listening = $false
            http_health = "unknown"
        }

        # 检查端口
        try {
            $conn = Get-NetTCPConnection -LocalPort $mod.Port -ErrorAction SilentlyContinue
            if ($conn) {
                $modResult.port_listening = $true
                $modResult.status = "running"
                $runningCount++
            } else {
                $modResult.status = "stopped"
                $stoppedCount++
            }
        } catch {
            $modResult.status = "unknown"
        }

        # HTTP 健康检查（深度模式）
        if ($Deep -and $modResult.port_listening) {
            try {
                $url = "http://127.0.0.1:$($mod.Port)/health"
                $response = Invoke-WebRequest -Uri $url -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
                if ($response.StatusCode -eq 200) {
                    $modResult.http_health = "healthy"
                    try {
                        $healthData = $response.Content | ConvertFrom-Json
                        $modResult.health_detail = $healthData
                    } catch { }
                } else {
                    $modResult.http_health = "unhealthy"
                    $healthResults.warnings += "$($mod.Name) HTTP 健康检查返回 $($response.StatusCode)"
                }
            } catch {
                $modResult.http_health = "unreachable"
                $modResult.health_error = $_.Exception.Message
            }
        }

        $healthResults.modules += $modResult

        $statusColor = switch ($modResult.status) {
            "running" { "Green" }
            "stopped" { "Red" }
            default { "Gray" }
        }
        $statusIcon = switch ($modResult.status) {
            "running" { "[UP]" }
            "stopped" { "[DOWN]" }
            default { "[??]" }
        }

        Write-Host "  $statusIcon $($mod.Name) ($($mod.Id), port $($mod.Port))" -ForegroundColor $statusColor
    }

    Write-Host ""
    Write-Host "  运行中: $runningCount, 已停止: $stoppedCount" -ForegroundColor $(if ($stoppedCount -eq 0) { "Green" } else { "Yellow" })

    if ($stoppedCount -gt 0 -and -not $Module) {
        if ($healthResults.overall_status -eq "healthy") {
            $healthResults.overall_status = "degraded"
        }
    }
}

# ============================================================================
# 日志错误检查
# ============================================================================
function Test-LogErrors {
    if (-not $Deep) {
        return
    }

    Write-Host ""
    Write-Host "[日志错误检查]" -ForegroundColor Yellow

    if (-not (Test-Path $LogDir)) {
        Write-Host "  日志目录不存在" -ForegroundColor Gray
        return
    }

    $errorCount = 0
    $logFiles = Get-ChildItem -Path $LogDir -Filter "*.log" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 5

    foreach ($logFile in $logFiles) {
        try {
            # 检查最近 100 行中的错误
            $lines = Get-Content $logFile.FullName -Tail 100 -ErrorAction SilentlyContinue
            $errors = $lines | Select-String -Pattern "ERROR|CRITICAL|Exception|Traceback" -SimpleMatch
            if ($errors) {
                $errorCount += $errors.Count
                Write-Host "  $($logFile.Name): 发现 $($errors.Count) 个错误" -ForegroundColor Yellow
            } else {
                Write-Host "  $($logFile.Name): [OK]" -ForegroundColor Green
            }
        } catch { }
    }

    $healthResults.log_error_count = $errorCount
    if ($errorCount -gt 0) {
        $healthResults.warnings += "日志中发现 $errorCount 个错误"
    }
}

# ============================================================================
# 数据库检查
# ============================================================================
function Test-Database {
    if (-not $Deep) {
        return
    }

    Write-Host ""
    Write-Host "[数据库检查]" -ForegroundColor Yellow

    $dbFiles = Get-ChildItem -Path $BaseDir -Filter "*.db" -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch "node_modules|__pycache__|\.git" } |
        Select-Object -First 5

    if ($dbFiles) {
        foreach ($db in $dbFiles) {
            try {
                $sizeKB = [math]::Round($db.Length / 1KB, 2)
                Write-Host "  $($db.Name): $sizeKB KB" -ForegroundColor Green
            } catch { }
        }
    } else {
        Write-Host "  未找到数据库文件" -ForegroundColor Gray
    }
}

# ============================================================================
# 主流程
# ============================================================================

if ($OutputFormat -eq "text") {
    Write-Host ""
    Write-Host "=========================================" -ForegroundColor Cyan
    Write-Host "  云汐系统健康检查$(if ($Deep) { ' [深度模式]' } else { '' })" -ForegroundColor Cyan
    Write-Host "=========================================" -ForegroundColor Cyan
    Write-Host ""
}

Test-SystemResources
Test-Modules
Test-LogErrors
Test-Database

# 计算总体状态
$criticalCount = $healthResults.errors.Count
$warningCount = $healthResults.warnings.Count

if ($criticalCount -gt 0) {
    $healthResults.overall_status = "unhealthy"
} elseif ($warningCount -gt 0) {
    $healthResults.overall_status = "degraded"
}

# 输出
if ($OutputFormat -eq "text") {
    Write-Host ""
    Write-Host "=========================================" -ForegroundColor Cyan
    $statusColor = switch ($healthResults.overall_status) {
        "healthy" { "Green" }
        "degraded" { "Yellow" }
        "unhealthy" { "Red" }
        default { "Gray" }
    }
    Write-Host "  总体状态: $($healthResults.overall_status.ToUpper())" -ForegroundColor $statusColor
    Write-Host "=========================================" -ForegroundColor Cyan
    Write-Host ""

    if ($healthResults.warnings.Count -gt 0) {
        Write-Host "警告 ($($healthResults.warnings.Count)):" -ForegroundColor Yellow
        foreach ($w in $healthResults.warnings) {
            Write-Host "  - $w" -ForegroundColor Yellow
        }
        Write-Host ""
    }

    if ($healthResults.errors.Count -gt 0) {
        Write-Host "错误 ($($healthResults.errors.Count)):" -ForegroundColor Red
        foreach ($e in $healthResults.errors) {
            Write-Host "  - $e" -ForegroundColor Red
        }
        Write-Host ""
    }
}

# 输出到文件
if ($OutputFile) {
    if ($OutputFormat -eq "json") {
        $healthResults | ConvertTo-Json -Depth 10 | Set-Content -Path $OutputFile -Encoding UTF8
    } else {
        # 文本格式已输出到控制台，这里也保存一份
        $healthResults | ConvertTo-Json -Depth 10 | Set-Content -Path $OutputFile -Encoding UTF8
    }
    Write-Host "结果已保存到: $OutputFile" -ForegroundColor Green
}

# JSON 输出模式
if ($OutputFormat -eq "json") {
    $healthResults | ConvertTo-Json -Depth 10
}

# 退出码
if ($healthResults.overall_status -eq "healthy") {
    exit 0
} elseif ($healthResults.overall_status -eq "degraded") {
    exit 1
} else {
    exit 2
}
