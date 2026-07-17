<#
.SYNOPSIS
    云汐系统 - 日志查看脚本
.DESCRIPTION
    查看和搜索各模块日志，支持：
    - 按模块查看日志
    - 实时跟踪（tail -f）
    - 按级别过滤（error/warning/info）
    - 按时间范围过滤
    - 关键词搜索
.PARAMETER Module
    模块名称，如 M1, M5, Gateway 等；或 all 查看所有
.PARAMETER Follow
    实时跟踪模式（类似 tail -f）
.PARAMETER Level
    日志级别过滤: debug, info, warning, error, critical
.PARAMETER Keyword
    关键词搜索
.PARAMETER Lines
    显示最后 N 行（默认 100）
.PARAMETER Since
    从指定时间开始（如 "2024-01-01 12:00:00" 或 "1h" "30m"）
.PARAMETER Until
    到指定时间结束
.PARAMETER LogDir
    日志目录（默认自动检测）
.PARAMETER ListModules
    列出可用的模块和日志文件
.EXAMPLE
    .\logs.ps1 -Module M1
    查看 M1 模块最近 100 行日志
.EXAMPLE
    .\logs.ps1 -Module Gateway -Follow
    实时跟踪 Gateway 日志
.EXAMPLE
    .\logs.ps1 -Module all -Level error
    查看所有模块的 error 级别日志
.EXAMPLE
    .\logs.ps1 -Module M5 -Keyword "timeout" -Since "1h"
    搜索 M5 模块最近 1 小时内含 "timeout" 的日志
.EXAMPLE
    .\logs.ps1 -ListModules
    列出所有可用的日志文件
#>

param(
    [string]$Module = "all",
    [switch]$Follow,
    [ValidateSet("debug", "info", "warning", "error", "critical")]
    [string]$Level = "",
    [string]$Keyword = "",
    [int]$Lines = 100,
    [string]$Since = "",
    [string]$Until = "",
    [string]$LogDir = "",
    [switch]$ListModules
)

# ============================================================
# 初始化
# ============================================================

$ErrorActionPreference = "SilentlyContinue"
$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Get-Location }
# 脚本在 scripts/ 子目录下，项目根目录是父目录
$ProjectRoot = Split-Path $ScriptDir -Parent

# 模块与日志文件映射
$ModuleLogMap = @{
    "Gateway"   = @("API-Gateway\logs", "API-Gateway\*.log")
    "M0"        = @("M0-principal-console\logs", "M0-principal-console\*.log")
    "M1"        = @("M1-agent-hub\logs", "M1-agent-hub\*.log")
    "M2"        = @("M2-skills-cluster\logs", "M2-skills-cluster\*.log")
    "M3"        = @("M3-edge-cloud\logs", "M3-edge-cloud\*.log")
    "M4"        = @("m4-scene-engine\logs", "m4-scene-engine\*.log")
    "M5"        = @("M5-tide-memory\logs", "M5-tide-memory\*.log")
    "M6"        = @("M6-hardware-peripheral\logs", "M6-hardware-peripheral\*.log")
    "M7"        = @("M7-workflow-builder\logs", "M7-workflow-builder\*.log")
    "M8"        = @("M8-control-tower\logs", "M8-control-tower\*.log")
    "M9"        = @("M9-dev-workshop\logs", "M9-dev-workshop\*.log")
    "M10"       = @("M10-system-guard\logs", "M10-system-guard\*.log")
    "M11"       = @("M11-mcp-bus\logs", "M11-mcp-bus\*.log")
    "M12"       = @("M12-security-shield\logs", "M12-security-shield\*.log")
}

# ============================================================
# 工具函数
# ============================================================

function Get-LogFiles {
    param([string]$ModuleName)

    $logFiles = @()

    if ($ModuleName -eq "all") {
        foreach ($mod in $ModuleLogMap.Keys) {
            $files = Get-LogFiles -ModuleName $mod
            $logFiles += $files
        }
    }
    elseif ($ModuleLogMap.ContainsKey($ModuleName)) {
        $logDirPath = Join-Path $ProjectRoot $ModuleLogMap[$ModuleName][0]
        $pattern = $ModuleLogMap[$ModuleName][1]

        if (Test-Path $logDirPath) {
            $files = Get-ChildItem $logDirPath -Filter "*.log" -Recurse -ErrorAction SilentlyContinue
            $logFiles += $files
        }

        # 也检查模块根目录下的 log 文件
        $modRoot = Split-Path $logDirPath -Parent
        $rootLogs = Get-ChildItem $modRoot -Filter "*.log" -ErrorAction SilentlyContinue
        $logFiles += $rootLogs
    }
    else {
        # 尝试模糊匹配
        foreach ($key in $ModuleLogMap.Keys) {
            if ($key -like "*$ModuleName*" -or $ModuleName -like "*$key*") {
                $files = Get-LogFiles -ModuleName $key
                $logFiles += $files
            }
        }
    }

    return $logFiles | Sort-Object FullName -Unique
}

function Get-LogLevelPattern {
    param([string]$Level)

    switch ($Level) {
        "debug"    { return "DEBUG|debug" }
        "info"     { return "INFO|info" }
        "warning"  { return "WARNING|WARN|warning|warn" }
        "error"    { return "ERROR|error" }
        "critical" { return "CRITICAL|FATAL|critical|fatal" }
        default    { return "" }
    }
}

function Convert-TimeString {
    param([string]$TimeStr)

    if ([string]::IsNullOrEmpty($TimeStr)) {
        return $null
    }

    # 尝试解析为绝对时间
    try {
        $date = [DateTime]::Parse($TimeStr)
        return $date
    }
    catch {}

    # 解析相对时间（如 1h, 30m, 2d）
    if ($TimeStr -match "^(\d+)([smhd])$") {
        $num = [int]$Matches[1]
        $unit = $Matches[2]

        $now = Get-Date
        switch ($unit) {
            "s" { return $now.AddSeconds(-$num) }
            "m" { return $now.AddMinutes(-$num) }
            "h" { return $now.AddHours(-$num) }
            "d" { return $now.AddDays(-$num) }
        }
    }

    return $null
}

function Test-LogLineInTimeRange {
    param(
        [string]$Line,
        [Nullable[DateTime]]$SinceTime,
        [Nullable[DateTime]]$UntilTime
    )

    if (-not $SinceTime -and -not $UntilTime) {
        return $true
    }

    # 尝试从日志行中提取时间戳
    # 常见格式: 2024-01-01 12:00:00, 2024-01-01T12:00:00, [2024-01-01 12:00:00]
    $timestampPatterns = @(
        "(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})",
        "\[(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})\]",
        "(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})"
    )

    foreach ($pattern in $timestampPatterns) {
        if ($Line -match $pattern) {
            try {
                $logTime = [DateTime]::Parse($Matches[1])
                if ($SinceTime -and $logTime -lt $SinceTime) { return $false }
                if ($UntilTime -and $logTime -gt $UntilTime) { return $false }
                return $true
            }
            catch {}
        }
    }

    # 无法解析时间戳时默认包含
    return $true
}

# ============================================================
# 列出模块
# ============================================================

function Show-ModuleList {
    Write-Host ""
    Write-Host "可用模块与日志文件:" -ForegroundColor Cyan
    Write-Host "------------------------"

    $foundAny = $false

    foreach ($mod in ($ModuleLogMap.Keys | Sort-Object)) {
        $files = Get-LogFiles -ModuleName $mod

        if ($files -and $files.Count -gt 0) {
            $foundAny = $true
            $totalSize = ($files | Measure-Object -Property Length -Sum).Sum
            $totalSizeKB = [math]::Round($totalSize / 1KB, 1)

            Write-Host ""
            Write-Host "  $mod" -ForegroundColor White
            foreach ($file in ($files | Sort-Object LastWriteTime -Descending | Select-Object -First 3)) {
                Write-Host "    - $($file.Name) ($($file.LastWriteTime.ToString('MM-dd HH:mm')), $totalSizeKB KB)"
            }
            if ($files.Count -gt 3) {
                Write-Host "    ... 共 $($files.Count) 个文件" -ForegroundColor Gray
            }
        }
    }

    if (-not $foundAny) {
        Write-Host ""
        Write-Host "  未找到任何日志文件" -ForegroundColor Yellow
        Write-Host "  日志可能输出到控制台或未配置文件日志" -ForegroundColor Gray
    }

    Write-Host ""
}

# ============================================================
# 查看日志
# ============================================================

function Show-Logs {
    $logFiles = Get-LogFiles -ModuleName $Module

    if (-not $logFiles -or $logFiles.Count -eq 0) {
        Write-Host ""
        Write-Host "[WARN] 未找到 $Module 的日志文件" -ForegroundColor Yellow
        Write-Host "提示: 使用 -ListModules 查看可用日志" -ForegroundColor Gray
        Write-Host ""
        return
    }

    # 解析时间范围
    $sinceTime = Convert-TimeString -TimeStr $Since
    $untilTime = Convert-TimeString -TimeStr $Until

    # 日志级别过滤模式
    $levelPattern = Get-LogLevelPattern -Level $Level

    # 收集所有匹配的日志行
    $allLines = [System.Collections.ArrayList]::new()

    foreach ($file in $logFiles) {
        try {
            $fileLines = Get-Content $file.FullName -Tail $Lines -ErrorAction Stop

            foreach ($line in $fileLines) {
                # 时间范围过滤
                if (-not (Test-LogLineInTimeRange -Line $line -SinceTime $sinceTime -UntilTime $untilTime)) {
                    continue
                }

                # 级别过滤
                if (-not [string]::IsNullOrEmpty($levelPattern)) {
                    if ($line -notmatch $levelPattern) {
                        continue
                    }
                }

                # 关键词过滤
                if (-not [string]::IsNullOrEmpty($Keyword)) {
                    if ($line -notmatch [regex]::Escape($Keyword)) {
                        continue
                    }
                }

                # 添加模块前缀
                $modPrefix = ""
                if ($Module -eq "all") {
                    foreach ($key in $ModuleLogMap.Keys) {
                        if ($file.FullName -match [regex]::Escape($ModuleLogMap[$key][0])) {
                            $modPrefix = "[$key] "
                            break
                        }
                    }
                }

                [void]$allLines.Add($modPrefix + $line)
            }
        }
        catch {}
    }

    # 显示结果
    if ($allLines.Count -eq 0) {
        Write-Host ""
        Write-Host "[INFO] 没有匹配的日志条目" -ForegroundColor Gray
        Write-Host ""
        return
    }

    # 只显示最后 N 行
    $displayLines = $allLines | Select-Object -Last $Lines

    Write-Host ""
    Write-Host "--- 日志输出 ($($displayLines.Count) 行, 来源 $($logFiles.Count) 个文件) ---" -ForegroundColor Cyan
    Write-Host ""

    foreach ($line in $displayLines) {
        # 按级别着色
        if ($line -match "ERROR|error|CRITICAL|critical|FATAL|fatal") {
            Write-Host $line -ForegroundColor Red
        }
        elseif ($line -match "WARNING|WARN|warning|warn") {
            Write-Host $line -ForegroundColor Yellow
        }
        elseif ($line -match "DEBUG|debug") {
            Write-Host $line -ForegroundColor Gray
        }
        else {
            Write-Host $line
        }
    }

    Write-Host ""
    Write-Host "--- 结束 ---" -ForegroundColor Cyan
    Write-Host ""
}

# ============================================================
# 实时跟踪模式
# ============================================================

function Follow-Logs {
    $logFiles = Get-LogFiles -ModuleName $Module

    if (-not $logFiles -or $logFiles.Count -eq 0) {
        Write-Host ""
        Write-Host "[WARN] 未找到 $Module 的日志文件用于跟踪" -ForegroundColor Yellow
        Write-Host ""
        return
    }

    # 选择最新的日志文件
    $latestFile = $logFiles | Sort-Object LastWriteTime -Descending | Select-Object -First 1

    Write-Host ""
    Write-Host "--- 实时跟踪: $($latestFile.Name) ---" -ForegroundColor Cyan
    Write-Host "按 Ctrl+C 退出" -ForegroundColor Gray
    Write-Host ""

    # 级别过滤模式
    $levelPattern = Get-LogLevelPattern -Level $Level

    try {
        Get-Content $latestFile.FullName -Tail $Lines -Wait -ErrorAction Stop | ForEach-Object {
            $line = $_

            # 级别过滤
            if (-not [string]::IsNullOrEmpty($levelPattern)) {
                if ($line -notmatch $levelPattern) {
                    return
                }
            }

            # 关键词过滤
            if (-not [string]::IsNullOrEmpty($Keyword)) {
                if ($line -notmatch [regex]::Escape($Keyword)) {
                    return
                }
            }

            # 着色输出
            if ($line -match "ERROR|error|CRITICAL|critical|FATAL|fatal") {
                Write-Host $line -ForegroundColor Red
            }
            elseif ($line -match "WARNING|WARN|warning|warn") {
                Write-Host $line -ForegroundColor Yellow
            }
            elseif ($line -match "DEBUG|debug") {
                Write-Host $line -ForegroundColor Gray
            }
            else {
                Write-Host $line
            }
        }
    }
    catch [System.Management.Automation.PipelineStoppedException] {
        Write-Host ""
        Write-Host "已停止跟踪" -ForegroundColor Gray
    }
    catch {
        Write-Host ""
        Write-Host "[ERROR] 跟踪失败: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# ============================================================
# 主流程
# ============================================================

function Main {
    if ($ListModules) {
        Show-ModuleList
        return
    }

    if ($Follow) {
        Follow-Logs
    }
    else {
        Show-Logs
    }
}

Main
