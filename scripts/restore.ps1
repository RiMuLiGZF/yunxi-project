<#
.SYNOPSIS
云汐系统恢复脚本
.DESCRIPTION
从备份中恢复云汐系统数据。支持完整恢复和选择性恢复。

.PARAMETER BackupPath
备份文件或目录路径（支持 .zip 或目录）

.PARAMETER RestoreDir
恢复目标目录，默认项目根目录

.PARAMETER Items
要恢复的项目，可选值：config, database, data, logs, all
默认恢复 config 和 database

.PARAMETER DryRun
试运行模式，只显示将要恢复的内容，不实际执行

.EXAMPLE
.\restore.ps1 -BackupPath "D:\backups\yunxi_full_20260101_120000.zip"
从指定备份完整恢复配置和数据库

.EXAMPLE
.\restore.ps1 -BackupPath "D:\backups\yunxi_full_20260101_120000" -Items config,database
从备份目录恢复配置和数据库

.EXAMPLE
.\restore.ps1 -BackupPath "backup.zip" -DryRun
试运行，查看将恢复哪些内容
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$BackupPath,

    [string]$RestoreDir = "",

    [ValidateSet("config", "database", "data", "logs", "all")]
    [string[]]$Items = @("config", "database"),

    [switch]$DryRun = $false
)

$ErrorActionPreference = "Stop"

# 获取项目根目录
$BaseDir = Split-Path -Parent $PSScriptRoot
if (-not $RestoreDir) {
    $RestoreDir = $BaseDir
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  云汐系统恢复" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  备份源: $BackupPath" -ForegroundColor White
Write-Host "  恢复目标: $RestoreDir" -ForegroundColor White
Write-Host "  恢复项目: $($Items -join ', ')" -ForegroundColor White
Write-Host "  试运行: $DryRun" -ForegroundColor White
Write-Host ""

# 检查备份是否存在
if (-not (Test-Path $BackupPath)) {
    Write-Host "[ERROR] 备份不存在: $BackupPath" -ForegroundColor Red
    exit 1
}

$tempExtractDir = ""
$sourceDir = ""

try {
    # 如果是 zip 文件，先解压
    if ((Get-Item $BackupPath).Extension -eq ".zip") {
        Write-Host "解压备份文件..." -ForegroundColor Yellow
        $tempExtractDir = Join-Path $env:TEMP "yunxi_restore_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
        New-Item -ItemType Directory -Path $tempExtractDir -Force | Out-Null
        Expand-Archive -Path $BackupPath -DestinationPath $tempExtractDir -Force
        $sourceDir = $tempExtractDir
    } else {
        $sourceDir = $BackupPath
    }

    # 读取元数据
    $metadataPath = Join-Path $sourceDir "backup_metadata.json"
    if (Test-Path $metadataPath) {
        $metadata = Get-Content $metadataPath -Raw | ConvertFrom-Json
        Write-Host "备份信息:" -ForegroundColor Yellow
        Write-Host "  时间: $($metadata.backup_time)" -ForegroundColor Gray
        Write-Host "  模式: $($metadata.backup_mode)" -ForegroundColor Gray
        Write-Host "  主机: $($metadata.hostname)" -ForegroundColor Gray
        Write-Host ""
    }

    # 确定要恢复的项目
    if ($Items -contains "all") {
        $ItemsToRestore = @("config", "database", "data", "logs")
    } else {
        $ItemsToRestore = $Items
    }

    $restoredCount = 0
    $skippedCount = 0

    # ========================================================================
    # 恢复配置文件
    # ========================================================================
    if ($ItemsToRestore -contains "config") {
        Write-Host "[1/4] 恢复配置文件..." -ForegroundColor Yellow

        $srcConfig = Join-Path $sourceDir "config"
        $destConfig = Join-Path $RestoreDir "config"

        if (Test-Path $srcConfig) {
            if ($DryRun) {
                Write-Host "  [DRY-RUN] 将从 $srcConfig 恢复到 $destConfig" -ForegroundColor Gray
            } else {
                # 备份现有配置
                if (Test-Path $destConfig) {
                    $backupExisting = "$destConfig.bak_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
                    Write-Host "  备份现有配置到: $backupExisting" -ForegroundColor Gray
                    Copy-Item $destConfig $backupExisting -Recurse -Force
                }

                Copy-Item $srcConfig $destConfig -Recurse -Force
                Write-Host "  [OK] 配置文件已恢复" -ForegroundColor Green
            }
            $restoredCount++
        } else {
            Write-Host "  [SKIP] 备份中无配置文件" -ForegroundColor Gray
            $skippedCount++
        }
    }

    # ========================================================================
    # 恢复数据库
    # ========================================================================
    if ($ItemsToRestore -contains "database") {
        Write-Host "[2/4] 恢复数据库..." -ForegroundColor Yellow

        $srcDb = Join-Path $sourceDir "database"
        $destDb = Join-Path $RestoreDir "data"

        if (Test-Path $srcDb) {
            if ($DryRun) {
                Write-Host "  [DRY-RUN] 将从 $srcDb 恢复到 $destDb" -ForegroundColor Gray
            } else {
                if (-not (Test-Path $destDb)) {
                    New-Item -ItemType Directory -Path $destDb -Force | Out-Null
                }

                # 恢复数据库文件
                $dbFiles = Get-ChildItem -Path $srcDb -Filter "*.db" -File
                foreach ($dbFile in $dbFiles) {
                    $destFile = Join-Path $destDb $dbFile.Name
                    if (Test-Path $destFile) {
                        $bakFile = "$destFile.bak_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
                        Copy-Item $destFile $bakFile -Force
                        Write-Host "  备份现有数据库: $bakFile" -ForegroundColor Gray
                    }
                    Copy-Item $dbFile.FullName $destFile -Force
                    Write-Host "  [OK] $($dbFile.Name)" -ForegroundColor Green
                }
            }
            $restoredCount++
        } else {
            Write-Host "  [SKIP] 备份中无数据库" -ForegroundColor Gray
            $skippedCount++
        }
    }

    # ========================================================================
    # 恢复用户数据
    # ========================================================================
    if ($ItemsToRestore -contains "data") {
        Write-Host "[3/4] 恢复用户数据..." -ForegroundColor Yellow

        $dataDirs = @("data", "user_data", "uploads", "assets")
        $restoredAny = $false

        foreach ($dir in $dataDirs) {
            $src = Join-Path $sourceDir $dir
            $dest = Join-Path $RestoreDir $dir

            if (Test-Path $src) {
                if ($DryRun) {
                    Write-Host "  [DRY-RUN] 将恢复 $dir" -ForegroundColor Gray
                } else {
                    if (Test-Path $dest) {
                        $bakDir = "$dest.bak_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
                        Move-Item $dest $bakDir -Force
                    }
                    Copy-Item $src $dest -Recurse -Force
                    Write-Host "  [OK] $dir" -ForegroundColor Green
                }
                $restoredAny = $true
            }
        }

        if ($restoredAny) {
            $restoredCount++
        } else {
            Write-Host "  [SKIP] 备份中无用户数据" -ForegroundColor Gray
            $skippedCount++
        }
    }

    # ========================================================================
    # 恢复日志
    # ========================================================================
    if ($ItemsToRestore -contains "logs") {
        Write-Host "[4/4] 恢复日志..." -ForegroundColor Yellow

        $srcLogs = Join-Path $sourceDir "logs"
        $destLogs = Join-Path $RestoreDir "logs_restored"

        if (Test-Path $srcLogs) {
            if ($DryRun) {
                Write-Host "  [DRY-RUN] 将恢复日志到 $destLogs" -ForegroundColor Gray
            } else {
                Copy-Item $srcLogs $destLogs -Recurse -Force
                Write-Host "  [OK] 日志已恢复到: $destLogs" -ForegroundColor Green
            }
            $restoredCount++
        } else {
            Write-Host "  [SKIP] 备份中无日志" -ForegroundColor Gray
            $skippedCount++
        }
    }

    # ========================================================================
    # 总结
    # ========================================================================
    Write-Host ""
    Write-Host "=========================================" -ForegroundColor Cyan
    $status = if ($DryRun) { "试运行完成" } else { "恢复完成" }
    Write-Host "  $status" -ForegroundColor $(if ($skippedCount -lt $ItemsToRestore.Count) { "Green" } else { "Yellow" })
    Write-Host "=========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  已恢复: $restoredCount 项" -ForegroundColor Green
    Write-Host "  跳过: $skippedCount 项" -ForegroundColor Gray
    Write-Host ""

    if (-not $DryRun) {
        Write-Host "  注意: 请重启服务以使配置生效" -ForegroundColor Yellow
        Write-Host ""
    }

    exit 0

} catch {
    Write-Host ""
    Write-Host "[ERROR] 恢复失败: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""

    # 清理临时目录
    if ($tempExtractDir -and (Test-Path $tempExtractDir)) {
        try {
            Remove-Item $tempExtractDir -Recurse -Force -ErrorAction SilentlyContinue
        } catch { }
    }

    exit 1
} finally {
    # 清理临时目录
    if ($tempExtractDir -and (Test-Path $tempExtractDir)) {
        try {
            Remove-Item $tempExtractDir -Recurse -Force -ErrorAction SilentlyContinue
        } catch { }
    }
}
