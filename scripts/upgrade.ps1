# 云汐系统升级脚本 (Windows PowerShell)
# 版本: 1.0.0
# 用途: 将系统升级到 V1.0

param(
    [string]$TargetVersion = "1.0.0",
    [string]$InstallPath = "C:\yunxi",
    [switch]$DryRun,
    [switch]$NoBackup,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  云汐系统升级脚本" -ForegroundColor Cyan
Write-Host "  目标版本: v$TargetVersion" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------------------
# 步骤 1: 检查当前版本
# ------------------------------------------------------------
Write-Host "[1/7] 检查当前版本..." -ForegroundColor Yellow

$currentVersion = "unknown"
$versionFile = Join-Path $InstallPath "VERSION"
if (Test-Path $versionFile) {
    $currentVersion = Get-Content $versionFile -Raw
    $currentVersion = $currentVersion.Trim()
}

Write-Host "  当前版本: $currentVersion"
Write-Host "  目标版本: $TargetVersion"

if ($currentVersion -eq $TargetVersion) {
    if (-not $Force) {
        Write-Host "  已经是目标版本，无需升级" -ForegroundColor Green
        exit 0
    }
    Write-Host "  强制重新升级" -ForegroundColor Yellow
}

# ------------------------------------------------------------
# 步骤 2: 备份当前数据（重要！）
# ------------------------------------------------------------
Write-Host "[2/7] 备份当前数据..." -ForegroundColor Yellow

if ($NoBackup) {
    Write-Host "  跳过备份（不推荐）" -ForegroundColor Red
} else {
    $backupDir = Join-Path $InstallPath "backups"
    $backupName = "pre_upgrade_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    $backupPath = Join-Path $backupDir $backupName

    if (-not (Test-Path $backupDir)) {
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    }

    Write-Host "  备份目录: $backupPath"

    # 备份数据目录
    $dataDir = Join-Path $InstallPath "data"
    if (Test-Path $dataDir) {
        Write-Host "  备份数据目录..." -ForegroundColor Gray
        Copy-Item -Path $dataDir -Destination (Join-Path $backupPath "data") -Recurse -Force
        Write-Host "  数据目录已备份" -ForegroundColor Green
    }

    # 备份配置
    $configDir = Join-Path $InstallPath "config"
    if (Test-Path $configDir) {
        Copy-Item -Path $configDir -Destination (Join-Path $backupPath "config") -Recurse -Force
        Write-Host "  配置文件已备份" -ForegroundColor Green
    }

    Write-Host "  备份完成: $backupPath" -ForegroundColor Green
}

# ------------------------------------------------------------
# 步骤 3: 停止服务
# ------------------------------------------------------------
Write-Host "[3/7] 停止服务..." -ForegroundColor Yellow

$stopScript = Join-Path $InstallPath "scripts\stop-all.ps1"
if (Test-Path $stopScript) {
    Write-Host "  正在停止所有服务..." -ForegroundColor Gray
    & $stopScript 2>&1 | Out-Null
    Write-Host "  服务已停止" -ForegroundColor Green
} else {
    Write-Host "  未找到停止脚本，请确保所有服务已停止" -ForegroundColor Yellow
}

# ------------------------------------------------------------
# 步骤 4: 更新代码
# ------------------------------------------------------------
Write-Host "[4/7] 更新代码文件..." -ForegroundColor Yellow

if ($DryRun) {
    Write-Host "  [模拟模式，不实际更新" -ForegroundColor Yellow
} else {
    # 需要更新的模块
    $modules = @(
        "shared",
        "M0-principal-console",
        "M1-agent-hub",
        "M8-control-tower",
        "API-Gateway",
        "scripts",
        "config"
    )

    foreach ($module in $modules) {
        $src = Join-Path $ProjectRoot $module
        $dst = Join-Path $InstallPath $module
        if (Test-Path $src) {
            if (Test-Path $dst) {
                # 备份旧版本
                $oldBackup = "$dst.old_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
                Move-Item $dst $oldBackup -Force
            }
            Copy-Item -Path $src -Destination $InstallPath -Recurse -Force
            Write-Host "  更新: $module" -ForegroundColor Green
        }
    }

    Write-Host "  代码更新完成" -ForegroundColor Green
}

# ------------------------------------------------------------
# 步骤 5: 更新依赖
# ------------------------------------------------------------
Write-Host "[5/7] 更新依赖..." -ForegroundColor Yellow

if ($DryRun) {
    Write-Host "  [模拟模式，不更新依赖]" -ForegroundColor Yellow
} else {
    $requirementsFile = Join-Path $ProjectRoot "requirements.txt"
    if (Test-Path $requirementsFile) {
        Write-Host "  更新 Python 依赖..." -ForegroundColor Gray
        pip install --upgrade pip 2>&1 | Out-Null
        pip install -r $requirementsFile --upgrade 2>&1 | Out-Null
        Write-Host "  依赖更新完成" -ForegroundColor Green
    } else {
        Write-Host "  未找到 requirements.txt" -ForegroundColor Yellow
    }
}

# ------------------------------------------------------------
# 步骤 6: 数据库迁移
# ------------------------------------------------------------
Write-Host "[6/7] 数据库迁移..." -ForegroundColor Yellow

if ($DryRun) {
    Write-Host "  [模拟模式，不执行迁移]" -ForegroundColor Yellow
} else {
    $migrationScript = Join-Path $InstallPath "M0-principal-console\src\database.py"
    if (Test-Path $migrationScript) {
        Write-Host "  执行数据库迁移..." -ForegroundColor Gray
        Push-Location (Join-Path $InstallPath "M0-principal-console")
        try {
            python -c "from src.database import init_db; init_db(); print('Migration done')" 2>&1 | Out-Null
            Write-Host "  数据库迁移完成" -ForegroundColor Green
        } catch {
            Write-Host "  警告: 数据库迁移可能需要手动检查" -ForegroundColor Yellow
            Write-Host "  错误: $($_.Exception.Message" -ForegroundColor Red
        }
        Pop-Location
    } else {
        Write-Host "  未找到迁移脚本" -ForegroundColor Yellow
    }
}

# ------------------------------------------------------------
# 步骤 7: 更新版本号并重启
# ------------------------------------------------------------
Write-Host "[7/7] 更新版本号..." -ForegroundColor Yellow

if ($DryRun) {
    Write-Host "  [模拟模式]" -ForegroundColor Yellow
} else {
    # 写入版本文件
    $TargetVersion | Out-File -FilePath (Join-Path $InstallPath "VERSION") -Encoding utf8
    Write-Host "  版本号已更新: $TargetVersion" -ForegroundColor Green

    # 更新 CHANGELOG
    $changelogSrc = Join-Path $ProjectRoot "CHANGELOG.md"
    $changelogDst = Join-Path $InstallPath "docs\CHANGELOG.md"
    if (Test-Path $changelogSrc) {
        $docsDir = Join-Path $InstallPath "docs"
        if (-not (Test-Path $docsDir)) {
            New-Item -ItemType Directory -Path $docsDir -Force | Out-Null
        }
        Copy-Item $changelogSrc $changelogDst -Force
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  升级完成！" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  版本: $currentVersion -> $TargetVersion"
    Write-Host ""
    Write-Host "  后续操作:" -ForegroundColor Yellow
    Write-Host "  1. 检查配置文件是否需要更新的项"
    Write-Host "  2. 启动服务验证: scripts\start-all.ps1"
    Write-Host "  3. 运行健康检查验证"
    Write-Host ""
    Write-Host "  如遇问题，可使用回滚脚本恢复:" -ForegroundColor Yellow
    Write-Host "  scripts\rollback.ps1 -BackupPath <备份路径>"
    Write-Host ""
}
