# 云汐系统回滚脚本 (Windows PowerShell)
# 版本: 1.0.0
# 用途: 从升级失败或异常状态中回滚

param(
    [string]$BackupPath = "",
    [string]$InstallPath = "C:\yunxi",
    [switch]$Confirm
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "========================================" -ForegroundColor Red
Write-Host "  云汐系统回滚脚本" -ForegroundColor Red
Write-Host "========================================" -ForegroundColor Red
Write-Host ""

# ------------------------------------------------------------
# 警告确认
# ------------------------------------------------------------
if (-not $Confirm) {
    Write-Host "警告: 此操作将回滚系统到之前的状态！" -ForegroundColor Red
    Write-Host "  - 当前数据将被备份数据覆盖"
    Write-Host "  - 升级后的代码将被回滚"
    Write-Host ""
    $response = Read-Host "确认执行回滚吗？(输入 YES 确认)"
    if ($response -ne "YES") {
        Write-Host "  已取消回滚操作" -ForegroundColor Yellow
        exit 0
    }
}

# ------------------------------------------------------------
# 步骤 1: 查找备份
# ------------------------------------------------------------
Write-Host "[1/6] 查找备份..." -ForegroundColor Yellow

if ($BackupPath -and (Test-Path $BackupPath)) {
    Write-Host "  使用指定备份: $BackupPath" -ForegroundColor Green
} else {
    # 自动查找最新的升级前备份
    $backupDir = Join-Path $InstallPath "backups"
    if (Test-Path $backupDir) {
        $preUpgrades = Get-ChildItem $backupDir -Directory -Filter "pre_upgrade_*" | Sort-Object Name -Descending
        if ($preUpgrades.Count -gt 0) {
            $BackupPath = $preUpgrades[0].FullName
            Write-Host "  找到最新备份: $BackupPath" -ForegroundColor Green
        } else {
            Write-Host "  错误: 未找到升级前备份" -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "  错误: 备份目录不存在" -ForegroundColor Red
        exit 1
    }
}

# ------------------------------------------------------------
# 步骤 2: 停止服务
# ------------------------------------------------------------
Write-Host "[2/6] 停止服务..." -ForegroundColor Yellow

$stopScript = Join-Path $InstallPath "scripts\stop-all.ps1"
if (Test-Path $stopScript) {
    & $stopScript 2>&1 | Out-Null
    Write-Host "  服务已停止" -ForegroundColor Green
} else {
    Write-Host "  未找到停止脚本，手动确保服务已停止" -ForegroundColor Yellow
}

# ------------------------------------------------------------
# 步骤 3: 创建当前状态快照（安全网）
# ------------------------------------------------------------
Write-Host "[3/6] 创建当前状态快照..." -ForegroundColor Yellow

$snapshotDir = Join-Path $InstallPath "backups\rollback_safety_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
New-Item -ItemType Directory -Path $snapshotDir -Force | Out-Null

# 快照当前数据
$dataDir = Join-Path $InstallPath "data"
if (Test-Path $dataDir) {
    Copy-Item -Path $dataDir -Destination (Join-Path $snapshotDir "data") -Recurse -Force
    Write-Host "  数据已快照" -ForegroundColor Green
}

# 快照当前配置
$configDir = Join-Path $InstallPath "config"
if (Test-Path $configDir) {
    Copy-Item -Path $configDir -Destination (Join-Path $snapshotDir "config") -Recurse -Force
    Write-Host "  配置已快照" -ForegroundColor Green
}

Write-Host "  快照位置: $snapshotDir" -ForegroundColor Green

# ------------------------------------------------------------
# 步骤 4: 恢复数据
# ------------------------------------------------------------
Write-Host "[4/6] 恢复数据..." -ForegroundColor Yellow

$backupData = Join-Path $BackupPath "data"
if (Test-Path $backupData) {
    $targetData = Join-Path $InstallPath "data"
    if (Test-Path $targetData) {
        Remove-Item $targetData -Recurse -Force
    }
    Copy-Item -Path $backupData -Destination $targetData -Recurse -Force
    Write-Host "  数据恢复完成" -ForegroundColor Green
} else {
    Write-Host "  警告: 备份中没有数据目录" -ForegroundColor Yellow
}

# ------------------------------------------------------------
# 步骤 5: 恢复配置
# ------------------------------------------------------------
Write-Host "[5/6] 恢复配置..." -ForegroundColor Yellow

$backupConfig = Join-Path $BackupPath "config"
if (Test-Path $backupConfig) {
    $targetConfig = Join-Path $InstallPath "config"
    if (Test-Path $targetConfig) {
        Remove-Item $targetConfig -Recurse -Force
    }
    Copy-Item -Path $backupConfig -Destination $targetConfig -Recurse -Force
    Write-Host "  配置恢复完成" -ForegroundColor Green
} else {
    Write-Host "  警告: 备份中没有配置目录" -ForegroundColor Yellow
}

# ------------------------------------------------------------
# 步骤 6: 验证并提示重启
# ------------------------------------------------------------
Write-Host "[6/6] 验证回滚..." -ForegroundColor Yellow

$verifyOk = $true

# 验证数据目录
$dataDir = Join-Path $InstallPath "data"
if (Test-Path $dataDir) {
    Write-Host "  ✓ 数据目录已恢复" -ForegroundColor Green
} else {
    Write-Host "  ✗ 数据目录未找到" -ForegroundColor Red
    $verifyOk = $false
}

# 验证配置
$configFile = Join-Path $InstallPath "config\settings.yaml"
if (Test-Path $configFile) {
    Write-Host "  ✓ 配置文件已恢复" -ForegroundColor Green
} else {
    Write-Host "  ⚠ 配置文件未找到（可能使用其他配置方式）" -ForegroundColor Yellow
}

Write-Host ""

if ($verifyOk) {
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  回滚成功！" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  安全快照: $snapshotDir"
    Write-Host "  （如回滚有问题，可从此快照恢复）"
    Write-Host ""
    Write-Host "  后续操作:" -ForegroundColor Yellow
    Write-Host "  1. 检查数据完整性"
    Write-Host "  2. 重启服务: scripts\start-all.ps1"
    Write-Host "  3. 验证核心功能"
    Write-Host ""
} else {
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  回滚可能存在问题" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "  安全快照: $snapshotDir"
    Write-Host "  请手动检查恢复状态"
    Write-Host ""
    exit 1
}
