<#
.SYNOPSIS
云汐系统备份脚本
.DESCRIPTION
备份云汐系统的关键数据，包括配置文件、数据库、日志等。
支持完整备份和增量备份两种模式。

.PARAMETER Mode
备份模式：full（完整备份）或 incremental（增量备份），默认 full

.PARAMETER BackupDir
备份输出目录，默认 backups/

.PARAMETER IncludeLogs
是否包含日志文件备份，默认 $false

.PARAMETER Compress
是否压缩备份，默认 $true

.PARAMETER RetainCount
保留的备份数量，超过自动删除最旧的备份，默认 10

.EXAMPLE
.\backup.ps1 -Mode full -BackupDir "D:\backups\yunxi"
执行完整备份到指定目录

.EXAMPLE
.\backup.ps1 -Mode incremental -IncludeLogs
执行增量备份，包含日志文件
#>

param(
    [ValidateSet("full", "incremental")]
    [string]$Mode = "full",

    [string]$BackupDir = "",

    [switch]$IncludeLogs = $false,

    [switch]$Compress = $true,

    [int]$RetainCount = 10
)

$ErrorActionPreference = "Continue"

# 获取项目根目录（脚本目录的上一级）
$BaseDir = Split-Path -Parent $PSScriptRoot
if (-not $BackupDir) {
    $BackupDir = Join-Path $BaseDir "backups"
}

# 确保备份目录存在
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

# 生成备份时间戳
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupName = "yunxi_${Mode}_${Timestamp}"
$BackupPath = Join-Path $BackupDir $BackupName

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  云汐系统备份" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  模式: $Mode" -ForegroundColor White
Write-Host "  备份目录: $BackupPath" -ForegroundColor White
Write-Host "  包含日志: $IncludeLogs" -ForegroundColor White
Write-Host "  压缩: $Compress" -ForegroundColor White
Write-Host ""

# 创建备份目录
New-Item -ItemType Directory -Path $BackupPath -Force | Out-Null

$successCount = 0
$failCount = 0

# ============================================================================
# 备份配置文件
# ============================================================================
Write-Host "[1/5] 备份配置文件..." -ForegroundColor Yellow

$configDir = Join-Path $BaseDir "config"
if (Test-Path $configDir) {
    $dest = Join-Path $BackupPath "config"
    try {
        Copy-Item -Path $configDir -Destination $dest -Recurse -Force
        Write-Host "  [OK] 配置文件已备份" -ForegroundColor Green
        $successCount++
    } catch {
        Write-Host "  [FAIL] 配置文件备份失败: $($_.Exception.Message)" -ForegroundColor Red
        $failCount++
    }
} else {
    Write-Host "  [SKIP] 配置目录不存在" -ForegroundColor Gray
}

# ============================================================================
# 备份数据库
# ============================================================================
Write-Host "[2/5] 备份数据库..." -ForegroundColor Yellow

# 查找 SQLite 数据库文件
$dbFiles = Get-ChildItem -Path $BaseDir -Filter "*.db" -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch "node_modules|__pycache__|\.git" }

if ($dbFiles) {
    $dbBackupDir = Join-Path $BackupPath "database"
    New-Item -ItemType Directory -Path $dbBackupDir -Force | Out-Null

    foreach ($dbFile in $dbFiles) {
        try {
            $relPath = $dbFile.FullName.Substring($BaseDir.Length).TrimStart("\")
            $destFile = Join-Path $dbBackupDir ($relPath -replace "\\", "_")
            Copy-Item -Path $dbFile.FullName -Destination $destFile -Force
            Write-Host "  [OK] 数据库: $($dbFile.Name)" -ForegroundColor Green
        } catch {
            Write-Host "  [FAIL] $($dbFile.Name): $($_.Exception.Message)" -ForegroundColor Red
            $failCount++
        }
    }
    $successCount++
} else {
    Write-Host "  [SKIP] 未找到数据库文件" -ForegroundColor Gray
}

# ============================================================================
# 备份用户数据
# ============================================================================
Write-Host "[3/5] 备份用户数据..." -ForegroundColor Yellow

$dataDirs = @("data", "user_data", "uploads", "assets")
foreach ($dir in $dataDirs) {
    $fullPath = Join-Path $BaseDir $dir
    if (Test-Path $fullPath) {
        $dest = Join-Path $BackupPath $dir
        try {
            Copy-Item -Path $fullPath -Destination $dest -Recurse -Force
            Write-Host "  [OK] $dir" -ForegroundColor Green
            $successCount++
        } catch {
            Write-Host "  [FAIL] $dir: $($_.Exception.Message)" -ForegroundColor Red
            $failCount++
        }
    }
}

# ============================================================================
# 备份日志（可选）
# ============================================================================
Write-Host "[4/5] 备份日志..." -ForegroundColor Yellow

if ($IncludeLogs) {
    $logDir = Join-Path $BaseDir "logs"
    if (Test-Path $logDir) {
        $dest = Join-Path $BackupPath "logs"
        try {
            Copy-Item -Path $logDir -Destination $dest -Recurse -Force
            Write-Host "  [OK] 日志已备份" -ForegroundColor Green
            $successCount++
        } catch {
            Write-Host "  [FAIL] 日志备份失败: $($_.Exception.Message)" -ForegroundColor Red
            $failCount++
        }
    } else {
        Write-Host "  [SKIP] 日志目录不存在" -ForegroundColor Gray
    }
} else {
    Write-Host "  [SKIP] 未启用日志备份" -ForegroundColor Gray
}

# ============================================================================
# 备份版本信息
# ============================================================================
Write-Host "[5/5] 备份元数据..." -ForegroundColor Yellow

try {
    $metadata = @{
        backup_time = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        backup_mode = $Mode
        backup_name = $BackupName
        project_root = $BaseDir
        hostname = $env:COMPUTERNAME
        username = $env:USERNAME
        os_version = [System.Environment]::OSVersion.VersionString
    }

    # 尝试获取 Git 版本信息
    try {
        $gitCommit = git -C $BaseDir rev-parse --short HEAD 2>$null
        if ($gitCommit) {
            $metadata["git_commit"] = $gitCommit
        }
    } catch { }

    $metadataPath = Join-Path $BackupPath "backup_metadata.json"
    $metadata | ConvertTo-Json -Depth 10 | Set-Content -Path $metadataPath -Encoding UTF8
    Write-Host "  [OK] 元数据已保存" -ForegroundColor Green
    $successCount++
} catch {
    Write-Host "  [FAIL] 元数据保存失败: $($_.Exception.Message)" -ForegroundColor Red
    $failCount++
}

# ============================================================================
# 压缩备份
# ============================================================================
if ($Compress) {
    Write-Host ""
    Write-Host "正在压缩备份..." -ForegroundColor Yellow
    try {
        $zipPath = "$BackupPath.zip"
        if (Test-Path $zipPath) {
            Remove-Item $zipPath -Force
        }
        Compress-Archive -Path "$BackupPath\*" -DestinationPath $zipPath -CompressionLevel Optimal -Force

        # 删除未压缩的目录
        Remove-Item $BackupPath -Recurse -Force
        $BackupPath = $zipPath

        $zipSize = (Get-Item $zipPath).Length / 1MB
        Write-Host "  [OK] 压缩完成: $([math]::Round($zipSize, 2)) MB" -ForegroundColor Green
    } catch {
        Write-Host "  [FAIL] 压缩失败: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# ============================================================================
# 清理旧备份
# ============================================================================
Write-Host ""
Write-Host "清理旧备份（保留最近 $RetainCount 份）..." -ForegroundColor Yellow

try {
    $backups = Get-ChildItem -Path $BackupDir -Filter "yunxi_${Mode}_*" |
        Sort-Object LastWriteTime -Descending

    if ($backups.Count -gt $RetainCount) {
        $oldBackups = $backups | Select-Object -Skip $RetainCount
        foreach ($old in $oldBackups) {
            try {
                Remove-Item $old.FullName -Recurse -Force
                Write-Host "  [DELETE] $($old.Name)" -ForegroundColor Gray
            } catch {
                Write-Host "  [FAIL] 删除 $($old.Name) 失败" -ForegroundColor Red
            }
        }
    } else {
        Write-Host "  [OK] 备份数量未超过限制 ($($backups.Count)/$RetainCount)" -ForegroundColor Gray
    }
} catch {
    Write-Host "  [WARN] 清理旧备份失败: $($_.Exception.Message)" -ForegroundColor Yellow
}

# ============================================================================
# 总结
# ============================================================================
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  备份完成" -ForegroundColor $(if ($failCount -eq 0) { "Green" } else { "Yellow" })
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  成功: $successCount 项" -ForegroundColor Green
Write-Host "  失败: $failCount 项" -ForegroundColor $(if ($failCount -eq 0) { "Gray" } else { "Red" })
Write-Host "  备份位置: $BackupPath" -ForegroundColor White
Write-Host ""

# 返回退出码
if ($failCount -eq 0) {
    exit 0
} else {
    exit 1
}
