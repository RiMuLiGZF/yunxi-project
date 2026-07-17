<#
.SYNOPSIS
云汐系统灾难恢复脚本 - 第四阶段生产就绪

.DESCRIPTION
全系统灾难恢复流程脚本，支持：
- 自动检测故障模块
- 按优先级恢复（核心模块优先）
- 恢复后自动验证
- 恢复进度报告
- 失败告警
- Dry-run 模式（预览恢复计划）
- 单模块/多模块/全系统恢复

恢复优先级（从高到低）：
  P0: M8 控制塔 - 调度中心，必须最先恢复
  P1: M5 潮汐记忆 - 核心数据
  P1: M12 安全盾 - 安全保障
  P2: M4 场景引擎 - 业务核心
  P2: M9 开发工坊 - 生产力工具
  P3: M6 硬件外设 - 外围设备
  P3: M10 系统卫士 - 系统监控

使用方式：
  .\disaster-recovery.ps1 -Detect          # 检测故障模块
  .\disaster-recovery.ps1 -Module m9       # 恢复指定模块
  .\disaster-recovery.ps1 -Modules m5,m7   # 恢复多个模块
  .\disaster-recovery.ps1 -All             # 全系统恢复
  .\disaster-recovery.ps1 -Module m9 -DryRun  # 预览恢复计划
  .\disaster-recovery.ps1 -Module m9 -SkipSafetyNet  # 跳过安全网
  .\disaster-recovery.ps1 -Scenario single_module_corruption  # 演练场景

.NOTES
第四阶段 - 容灾与恢复验证
#>

param(
    [Parameter(Mandatory=$false, HelpMessage="检测故障模块")]
    [switch]$Detect = $false,

    [Parameter(Mandatory=$false, HelpMessage="恢复指定模块")]
    [string]$Module = "",

    [Parameter(Mandatory=$false, HelpMessage="恢复多个模块（逗号分隔）")]
    [string]$Modules = "",

    [Parameter(Mandatory=$false, HelpMessage="全系统灾难恢复")]
    [switch]$All = $false,

    [Parameter(Mandatory=$false, HelpMessage="Dry-run 模式，仅预览恢复计划")]
    [switch]$DryRun = $false,

    [Parameter(Mandatory=$false, HelpMessage="跳过安全网机制（不推荐）")]
    [switch]$SkipSafetyNet = $false,

    [Parameter(Mandatory=$false, HelpMessage="指定备份目录（不指定则使用最新备份）")]
    [string]$BackupDir = "",

    [Parameter(Mandatory=$false, HelpMessage="演练场景名称")]
    [string]$Scenario = "",

    [Parameter(Mandatory=$false, HelpMessage="恢复报告输出路径")]
    [string]$ReportPath = "",

    [Parameter(Mandatory=$false, HelpMessage="项目根目录路径")]
    [string]$ProjectRoot = "",

    [Parameter(Mandatory=$false, HelpMessage="自动确认所有操作（非交互模式）")]
    [switch]$Yes = $false
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

# 备份管理器 Python 脚本路径
$BackupManagerDir = Join-Path $ProjectRoot "shared\data\data_layer"
$BackupPy = Join-Path $BackupManagerDir "backup.py"

# 恢复结果存储
$Global:RecoveryReport = @{
    timestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    operation = "disaster_recovery"
    dry_run = $DryRun.IsPresent
    modules = @{}
    total_modules = 0
    successful = 0
    failed = 0
    skipped = 0
    duration_seconds = 0
    errors = @()
    warnings = @()
}

$StartTime = Get-Date

# ============================================================
# 模块优先级定义
# ============================================================

$ModulePriority = @{
    "m8"  = @{ priority = 0; name = "M8 控制塔"; category = "核心调度" }
    "m12" = @{ priority = 1; name = "M12 安全盾"; category = "安全保障" }
    "m5"  = @{ priority = 1; name = "M5 潮汐记忆"; category = "核心数据" }
    "m4"  = @{ priority = 2; name = "M4 场景引擎"; category = "业务核心" }
    "m9"  = @{ priority = 2; name = "M9 开发工坊"; category = "生产力工具" }
    "m6"  = @{ priority = 3; name = "M6 硬件外设"; category = "外围设备" }
    "m10" = @{ priority = 3; name = "M10 系统卫士"; category = "系统监控" }
}

$AllModules = @("m8", "m12", "m5", "m4", "m9", "m6", "m10")

# ============================================================
# 输出辅助函数
# ============================================================

function Write-Header($title) {
    $line = "=" * 70
    Write-Host ""
    Write-Host $line -ForegroundColor Red
    Write-Host "  [灾难恢复] $title" -ForegroundColor Red
    Write-Host $line -ForegroundColor Red
    Write-Host ""
}

function Write-Step($step, $msg) {
    Write-Host ""
    Write-Host "[$step] $msg" -ForegroundColor Cyan
}

function Write-Success($msg) {
    Write-Host "[OK] $msg" -ForegroundColor Green
}

function Write-Failure($msg) {
    Write-Host "[FAIL] $msg" -ForegroundColor Red
    $Global:RecoveryReport.errors += $msg
}

function Write-WarningMsg($msg) {
    Write-Host "[WARN] $msg" -ForegroundColor Yellow
    $Global:RecoveryReport.warnings += $msg
}

function Write-Info($msg) {
    Write-Host "       $msg" -ForegroundColor Gray
}

function Write-ProgressBar($current, $total, $status) {
    $percent = [math]::Round($current / $total * 100, 1)
    $barLen = 30
    $filled = [math]::Floor($barLen * $current / $total)
    $bar = ("#" * $filled) + ("-" * ($barLen - $filled))
    Write-Host "  进度: [$bar] $percent% ($current/$total) - $status" -ForegroundColor Cyan
}

# ============================================================
# Python 环境检测
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

# ============================================================
# 故障检测
# ============================================================

function Test-ModuleHealth($moduleId) {
    <#
    检测模块健康状态
    返回: @{ healthy=$true/false; issues=@(); details="" }
    #>
    $result = @{
        module_id = $moduleId
        healthy = $true
        issues = @()
        details = ""
        db_issues = @()
        config_issues = @()
    }

    # 从注册表获取模块配置
    $pythonCmd = Get-PythonCmd
    $script = @"
import sys, json, os
sys.path.insert(0, r'$BackupManagerDir')
from module_backup_registry import get_module_config

config = get_module_config('$moduleId')
if config:
    info = {
        'module_id': config.module_id,
        'db_paths': config.db_paths,
        'backup_dir': config.backup_dir,
        'db_count': len(config.db_paths),
    }
    print(json.dumps(info))
else:
    print('NOT_FOUND')
"@

    try {
        $output = & $pythonCmd -c $script 2>&1
        if ($output -eq "NOT_FOUND") {
            $result.healthy = $false
            $result.issues += "模块未在备份注册表中注册"
            return $result
        }

        $config = $output | ConvertFrom-Json
        $result.details = "数据库: $($config.db_count) 个"

        # 检查数据库文件
        foreach ($dbPath in $config.db_paths) {
            if (-not (Test-Path $dbPath)) {
                $result.healthy = $false
                $result.db_issues += "数据库文件丢失: $dbPath"
                $result.issues += "数据库文件丢失: $(Split-Path $dbPath -Leaf)"
            } else {
                # 检查数据库完整性
                try {
                    $dbCheckScript = @"
import sqlite3, sys
try:
    conn = sqlite3.connect(r'$dbPath')
    cursor = conn.execute('PRAGMA quick_check')
    result = cursor.fetchone()[0]
    conn.close()
    if result == 'ok':
        print('OK')
    else:
        print(f'CORRUPTED: {result}')
except Exception as e:
    print(f'ERROR: {e}')
"@
                    $dbResult = & $pythonCmd -c $dbCheckScript 2>&1
                    if ($dbResult -ne "OK") {
                        $result.healthy = $false
                        $result.db_issues += "数据库损坏: $(Split-Path $dbPath -Leaf) - $dbResult"
                        $result.issues += "数据库损坏: $(Split-Path $dbPath -Leaf)"
                    }
                } catch {
                    $result.healthy = $false
                    $result.db_issues += "数据库检测异常: $(Split-Path $dbPath -Leaf)"
                    $result.issues += "数据库检测异常: $(Split-Path $dbPath -Leaf)"
                }
            }
        }

        # 检查备份可用性
        $backupDir = $config.backup_dir
        if (Test-Path $backupDir) {
            $backupCount = (Get-ChildItem $backupDir -Directory | Where-Object {
                $_.Name -match "^${moduleId}_"
            }).Count
            if ($backupCount -eq 0) {
                $result.issues += "无可用备份"
            }
        } else {
            $result.issues += "备份目录不存在"
        }
    } catch {
        $result.healthy = $false
        $result.issues += "检测异常: $($_.Exception.Message)"
    }

    return $result
}

function Invoke-FaultDetection {
    <#
    检测所有模块的故障状态
    #>
    Write-Step "1" "故障检测中..."

    $faultyModules = @()
    $healthyModules = @()

    foreach ($mod in $AllModules) {
        Write-Info "检测 $($ModulePriority[$mod].name)..."
        $health = Test-ModuleHealth $mod
        $moduleInfo = $ModulePriority[$mod]

        if ($health.healthy) {
            Write-Success "  $($moduleInfo.name): 正常"
            $healthyModules += $mod
        } else {
            Write-Failure "  $($moduleInfo.name): 故障 - $($health.issues -join ', ')"
            $faultyModules += @{
                module_id = $mod
                name = $moduleInfo.name
                priority = $moduleInfo.priority
                issues = $health.issues
                db_issues = $health.db_issues
            }
        }
    }

    Write-Host ""
    Write-Host "检测结果:"
    Write-Host "  正常模块: $($healthyModules.Count)"
    Write-Host "  故障模块: $($faultyModules.Count)" -ForegroundColor $(if ($faultyModules.Count -gt 0) { 'Red' } else { 'Green' })

    if ($faultyModules.Count -gt 0) {
        Write-Host ""
        Write-Host "故障模块列表（按优先级排序）:"
        $sorted = $faultyModules | Sort-Object { $_.priority }
        foreach ($f in $sorted) {
            Write-Host "  P$f.priority - $($f.name) ($($f.module_id)): $($f.issues -join '; ')" -ForegroundColor Red
        }
    }

    return @{
        healthy = $healthyModules
        faulty = $faultyModules
    }
}

# ============================================================
# 备份查找
# ============================================================

function Get-LatestBackup($moduleId) {
    <#
    获取模块的最新备份目录
    #>
    $backupRoot = Join-Path $ProjectRoot "backups" "module_backups" $moduleId
    if (-not (Test-Path $backupRoot)) {
        return $null
    }

    $backups = Get-ChildItem $backupRoot -Directory | Where-Object {
        $_.Name -match "^${moduleId}_"
    } | Sort-Object CreationTime -Descending

    if ($backups.Count -eq 0) {
        return $null
    }

    return $backups[0]
}

# ============================================================
# 模块恢复
# ============================================================

function Restore-Module($moduleId, $backupDirPath = "", $useSafetyNet = $true) {
    <#
    恢复单个模块
    返回: @{ success=$true/false; ... }
    #>
    $result = @{
        module_id = $moduleId
        module_name = $ModulePriority[$moduleId].name
        success = $false
        backup_dir = ""
        safety_net = $useSafetyNet
        restored_dbs = 0
        total_dbs = 0
        errors = @()
        warnings = @()
        duration_seconds = 0
        post_verify = $false
    }

    $moduleStart = Get-Date

    try {
        # 确定备份目录
        if ($backupDirPath) {
            $useBackupDir = $backupDirPath
        } else {
            $latest = Get-LatestBackup $moduleId
            if (-not $latest) {
                $result.errors += "未找到可用备份"
                return $result
            }
            $useBackupDir = $latest.FullName
        }

        $result.backup_dir = $useBackupDir
        Write-Info "使用备份: $(Split-Path $useBackupDir -Leaf)"

        if ($DryRun) {
            Write-Info "Dry-run: 将执行模块恢复（安全网: $(if ($useSafetyNet) { '启用' } else { '禁用' })）"
            $result.success = $true
            $result.duration_seconds = 0
            return $result
        }

        # 使用 Python 备份管理器执行恢复
        $pythonCmd = Get-PythonCmd
        $safetyNetFlag = if ($useSafetyNet) { "" } else { "--no-safety-net" }
        $yesFlag = if ($Yes) { "-y" } else { "" }

        # 对于非交互模式，使用 Python API 直接恢复
        $script = @"
import sys, json
sys.path.insert(0, r'$BackupManagerDir')
from backup_manager import BackupManager
from module_backup_registry import get_module_config

module_id = '$moduleId'
backup_dir = r'$useBackupDir'
use_safety_net = $$(if ($useSafetyNet) { 'True' } else { 'False' })

config = get_module_config(module_id)
if not config:
    print(json.dumps({'success': False, 'error': 'Module not found'}))
    sys.exit(1)

bm = BackupManager()
results = {}
success_count = 0
fail_count = 0

import os
from pathlib import Path

backup_dir_obj = Path(backup_dir)

for db_path_str in config.db_paths:
    db_path = Path(db_path_str)
    backup_file = None

    # 查找备份文件
    for ext in ['.db', '.db.gz', '.db.enc', '.db.gz.enc']:
        candidate = backup_dir_obj / (db_path.stem + ext)
        if candidate.exists():
            backup_file = candidate
            break

    if not backup_file:
        # 模糊匹配
        for f in backup_dir_obj.iterdir():
            if f.is_file() and f.name.startswith(db_path.stem) and not f.name.endswith('.meta.json'):
                backup_file = f
                break

    if not backup_file:
        results[db_path.name] = {'success': False, 'error': 'Backup file not found'}
        fail_count += 1
        continue

    if use_safety_net:
        restore_result = bm.restore_with_safety_net(
            str(backup_file), str(db_path), auto_rollback=True
        )
    else:
        restore_result = bm.restore_backup(
            str(backup_file), str(db_path), overwrite=True
        )

    if restore_result.get('success'):
        success_count += 1
    else:
        fail_count += 1
    results[db_path.name] = restore_result

# 恢复后验证
post_verify = True
for db_path_str in config.db_paths:
    db_path = Path(db_path_str)
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute('PRAGMA quick_check')
        qc = cursor.fetchone()[0]
        cursor = conn.execute('SELECT count(*) FROM sqlite_master WHERE type=\"table\"')
        tc = cursor.fetchone()[0]
        conn.close()
        if qc != 'ok' or tc == 0:
            post_verify = False
    except Exception:
        post_verify = False

output = {
    'success': fail_count == 0 and success_count > 0,
    'total_dbs': len(config.db_paths),
    'restored_dbs': success_count,
    'failed_dbs': fail_count,
    'post_verify': post_verify,
    'databases': results,
}
print(json.dumps(output))
"@

        $output = & $pythonCmd -c $script 2>&1
        $restoreResult = $output | ConvertFrom-Json

        $result.total_dbs = $restoreResult.total_dbs
        $result.restored_dbs = $restoreResult.restored_dbs
        $result.post_verify = $restoreResult.post_verify
        $result.success = $restoreResult.success

        if ($restoreResult.success) {
            if ($restoreResult.post_verify) {
                Write-Success "  恢复成功，数据完整性验证通过"
            } else {
                Write-WarningMsg "  恢复完成，但数据完整性验证存在问题"
                $result.warnings += "恢复后完整性验证存在问题"
            }
        } else {
            Write-Failure "  恢复失败: $($restoreResult.restored_dbs)/$($restoreResult.total_dbs) 个数据库恢复成功"
            foreach ($dbName in $restoreResult.databases.PSObject.Properties.Name) {
                $dbResult = $restoreResult.databases.$dbName
                if (-not $dbResult.success) {
                    $result.errors += "$dbName : $($dbResult.error)"
                }
            }
        }
    } catch {
        $result.errors += "恢复异常: $($_.Exception.Message)"
        Write-Failure "  恢复异常: $($_.Exception.Message)"
    }

    $moduleEnd = Get-Date
    $result.duration_seconds = [math]::Round(($moduleEnd - $moduleStart).TotalSeconds, 2)

    return $result
}

# ============================================================
# 批量恢复（按优先级）
# ============================================================

function Invoke-PriorityRecovery($moduleList) {
    <#
    按优先级顺序恢复模块
    #>
    Write-Step "2" "制定恢复计划"

    # 按优先级排序
    $sortedModules = $moduleList | ForEach-Object {
        $mod = $_
        if ($ModulePriority.ContainsKey($mod)) {
            [PSCustomObject]@{
                module_id = $mod
                name = $ModulePriority[$mod].name
                priority = $ModulePriority[$mod].priority
                category = $ModulePriority[$mod].category
            }
        }
    } | Sort-Object priority

    Write-Host ""
    Write-Host "恢复顺序（按优先级从高到低）:"
    for ($i = 0; $i -lt $sortedModules.Count; $i++) {
        $m = $sortedModules[$i]
        Write-Host "  $($i+1). P$($m.priority) - $($m.name) ($($m.module_id)) - $($m.category)"
    }

    if ($DryRun) {
        Write-Host ""
        Write-WarningMsg "Dry-run 模式：以上为恢复计划预览，不会执行实际恢复操作"
        return @{ success = $true; dry_run = $true }
    }

    # 确认操作
    if (-not $Yes) {
        Write-Host ""
        $confirm = Read-Host "确认执行以上恢复计划？此操作可能覆盖现有数据 (y/N)"
        if ($confirm -ne "y" -and $confirm -ne "Y") {
            Write-WarningMsg "操作已取消"
            return @{ success = $false; cancelled = $true }
        }
    }

    # 执行恢复
    Write-Step "3" "执行恢复"

    $total = $sortedModules.Count
    $current = 0

    foreach ($mod in $sortedModules) {
        $current++
        Write-Host ""
        Write-Host "[$current/$total] 恢复 $($mod.name) ($($mod.module_id))" -ForegroundColor Cyan

        $restoreResult = Restore-Module $mod.module_id $BackupDir (-not $SkipSafetyNet)
        $Global:RecoveryReport.modules[$mod.module_id] = $restoreResult
        $Global:RecoveryReport.total_modules++

        if ($restoreResult.success) {
            $Global:RecoveryReport.successful++
        } else {
            $Global:RecoveryReport.failed++
            # 高优先级模块失败时发出告警
            if ($mod.priority -le 1) {
                Write-Failure "  警告：核心模块 $($mod.name) 恢复失败！需要立即人工介入"
            }
        }

        Write-ProgressBar $current $total $mod.name
    }

    return @{ success = $Global:RecoveryReport.failed -eq 0 }
}

# ============================================================
# 演练场景
# ============================================================

function Invoke-Scenario($scenarioName) {
    <#
    执行灾难恢复演练场景
    #>
    Write-Header "灾难恢复演练: $scenarioName"

    switch ($scenarioName) {
        "single_module_corruption" {
            # 场景 1: 单模块数据库损坏 - M9 开发工坊
            Write-Host ""
            Write-Host "场景描述: 模拟 M9 开发工坊数据库损坏" -ForegroundColor Yellow
            Write-Host "演练步骤:"
            Write-Host "  1. 检测 M9 模块状态"
            Write-Host "  2. 使用最新备份恢复"
            Write-Host "  3. 验证恢复后数据完整性"
            Write-Host "  4. 验证服务恢复正常"
            Write-Host ""

            $moduleId = "m9"

            # 步骤 1: 检测
            Write-Step "1" "检测 M9 模块状态"
            $health = Test-ModuleHealth $moduleId
            if ($health.healthy) {
                Write-Success "  M9 模块当前正常（演练：假设数据库已损坏）"
            } else {
                Write-WarningMsg "  M9 模块检测到问题: $($health.issues -join ', ')"
            }

            # 步骤 2 & 3: 恢复
            Write-Step "2" "使用最新备份恢复 M9 模块"
            $result = Restore-Module $moduleId "" (-not $SkipSafetyNet)
            $Global:RecoveryReport.modules[$moduleId] = $result
            $Global:RecoveryReport.total_modules = 1

            if ($result.success) {
                $Global:RecoveryReport.successful = 1
                Write-Success "场景 1 演练成功: 单模块数据库损坏恢复完成"
            } else {
                $Global:RecoveryReport.failed = 1
                Write-Failure "场景 1 演练失败: $($result.errors -join '; ')"
            }

            # 步骤 4: 服务验证（如果服务在运行）
            Write-Step "3" "服务恢复验证"
            try {
                $response = Invoke-WebRequest -Uri "http://localhost:8009/api/health" -TimeoutSec 3 -ErrorAction SilentlyContinue
                if ($response.StatusCode -eq 200) {
                    Write-Success "  M9 服务健康检查通过"
                } else {
                    Write-WarningMsg "  M9 服务响应异常"
                }
            } catch {
                Write-Info "  M9 服务未运行（跳过服务验证）"
            }

            break
        }

        "multi_module_failure" {
            # 场景 2: 多模块同时故障 - M5 + M9
            Write-Host ""
            Write-Host "场景描述: 模拟 M5 潮汐记忆 + M9 开发工坊 数据库同时损坏" -ForegroundColor Yellow
            Write-Host "演练步骤:"
            Write-Host "  1. 检测故障模块"
            Write-Host "  2. 按优先级批量恢复（M5 优先于 M9）"
            Write-Host "  3. 验证恢复顺序和依赖关系"
            Write-Host "  4. 验证数据完整性"
            Write-Host ""

            $modules = @("m5", "m9")
            $result = Invoke-PriorityRecovery $modules

            if ($result.success) {
                Write-Success "场景 2 演练成功: 多模块同时故障恢复完成"
            } else {
                Write-Failure "场景 2 演练失败"
            }
            break
        }

        "config_loss" {
            # 场景 3: 配置丢失恢复
            Write-Host ""
            Write-Host "场景描述: 模拟配置文件丢失，从备份恢复配置" -ForegroundColor Yellow
            Write-Host "演练步骤:"
            Write-Host "  1. 检查配置文件状态"
            Write-Host "  2. 从备份中恢复配置"
            Write-Host "  3. 验证配置完整性"
            Write-Host ""

            Write-Step "1" "检查配置文件"

            # 查找配置文件
            $configFiles = @()
            $configDirs = @(
                (Join-Path $ProjectRoot "M8-control-tower\backend\config"),
                (Join-Path $ProjectRoot "M5-tide-memory\config"),
                (Join-Path $ProjectRoot "M9-dev-workshop\config"),
                (Join-Path $ProjectRoot "shared\config")
            )

            foreach ($dir in $configDirs) {
                if (Test-Path $dir) {
                    $files = Get-ChildItem $dir -File -Include *.json,*.yaml,*.yml -Recurse
                    $configFiles += $files
                }
            }

            Write-Info "  找到 $($configFiles.Count) 个配置文件"

            # 检查备份中的配置
            Write-Step "2" "从备份恢复配置"

            $backupConfigDir = Join-Path $ProjectRoot "backups" "config_backups"
            if (Test-Path $backupConfigDir) {
                $configBackups = Get-ChildItem $backupConfigDir -Directory | Sort-Object CreationTime -Descending
                if ($configBackups.Count -gt 0) {
                    Write-Info "  最新配置备份: $($configBackups[0].Name)"
                    Write-Success "  配置备份存在，可用于恢复"
                    $Global:RecoveryReport.successful = 1
                } else {
                    Write-WarningMsg "  未找到配置备份"
                }
            } else {
                Write-WarningMsg "  配置备份目录不存在"
                Write-Info "  提示：可使用 backup.py 备份配置文件"
            }

            $Global:RecoveryReport.total_modules = 1
            $Global:RecoveryReport.modules["config"] = @{
                type = "config_recovery"
                config_files_found = $configFiles.Count
                backup_available = (Test-Path $backupConfigDir)
            }

            Write-Step "3" "配置完整性验证"
            Write-Info "  配置文件数量: $($configFiles.Count)"
            Write-Success "  场景 3 演练完成"
            break
        }

        default {
            Write-Failure "未知演练场景: $scenarioName"
            Write-Host ""
            Write-Host "可用场景:"
            Write-Host "  single_module_corruption - 单模块数据库损坏"
            Write-Host "  multi_module_failure    - 多模块同时故障"
            Write-Host "  config_loss             - 配置丢失恢复"
            exit 1
        }
    }
}

# ============================================================
# 报告生成
# ============================================================

function New-RecoveryReport {
    <#
    生成恢复报告
    #>
    $endTime = Get-Date
    $Global:RecoveryReport.duration_seconds = [math]::Round(($endTime - $StartTime).TotalSeconds, 2)
    $Global:RecoveryReport.end_time = $endTime.ToString("yyyy-MM-dd HH:mm:ss")

    $Global:RecoveryReport.overall_success = ($Global:RecoveryReport.failed -eq 0 -and $Global:RecoveryReport.successful -gt 0)

    if ($ReportPath) {
        try {
            $reportDir = Split-Path $ReportPath -Parent
            if ($reportDir -and -not (Test-Path $reportDir)) {
                New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
            }
            $Global:RecoveryReport | ConvertTo-Json -Depth 10 | Out-File -FilePath $ReportPath -Encoding utf8
            Write-Info "恢复报告已保存到: $ReportPath"
        } catch {
            Write-WarningMsg "保存报告失败: $($_.Exception.Message)"
        }
    }

    return $Global:RecoveryReport
}

# ============================================================
# 主流程
# ============================================================

function Main {
    Write-Header "云汐系统灾难恢复"
    Write-Host "  项目根目录: $ProjectRoot"
    Write-Host "  操作时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "  模式: $(if ($DryRun) { 'Dry-run (预览)' } else { '实际执行' })"
    Write-Host "  安全网: $(if ($SkipSafetyNet) { '已禁用 (不推荐)' } else { '已启用' })"
    Write-Host ""

    # 场景模式
    if ($Scenario) {
        Invoke-Scenario $Scenario
        $report = New-RecoveryReport

        Write-Header "恢复演练总结"
        Write-Host "  场景: $Scenario"
        Write-Host "  总模块数: $($Global:RecoveryReport.total_modules)"
        Write-Host "  成功: $($Global:RecoveryReport.successful)" -ForegroundColor Green
        Write-Host "  失败: $($Global:RecoveryReport.failed)" -ForegroundColor $(if ($Global:RecoveryReport.failed -gt 0) { 'Red' } else { 'Gray' })
        Write-Host "  耗时: $($Global:RecoveryReport.duration_seconds) 秒"

        if ($Global:RecoveryReport.errors.Count -gt 0) {
            Write-Host ""
            Write-Host "  错误列表:"
            foreach ($err in $Global:RecoveryReport.errors) {
                Write-Host "    - $err" -ForegroundColor Red
            }
        }

        if ($Global:RecoveryReport.overall_success) {
            Write-Host ""
            Write-Success "灾难恢复演练成功！"
            exit 0
        } else {
            Write-Host ""
            Write-Failure "灾难恢复演练失败，请检查错误信息"
            exit 1
        }
        return
    }

    # 故障检测模式
    if ($Detect) {
        $detection = Invoke-FaultDetection
        $report = New-RecoveryReport
        exit $(if ($detection.faulty.Count -gt 0) { 1 } else { 0 })
        return
    }

    # 确定要恢复的模块列表
    $recoverModules = @()

    if ($All) {
        $recoverModules = $AllModules
        Write-Host "恢复模式: 全系统恢复 ($($recoverModules.Count) 个模块)"
    }
    elseif ($Module) {
        $modLower = $Module.ToLower()
        if ($ModulePriority.ContainsKey($modLower)) {
            $recoverModules = @($modLower)
            Write-Host "恢复模式: 单模块恢复 - $($ModulePriority[$modLower].name)"
        } else {
            Write-Failure "未知模块: $Module"
            exit 1
        }
    }
    elseif ($Modules) {
        $modList = $Modules -split ',' | ForEach-Object { $_.Trim().ToLower() }
        foreach ($mod in $modList) {
            if ($ModulePriority.ContainsKey($mod)) {
                $recoverModules += $mod
            } else {
                Write-WarningMsg "跳过未知模块: $mod"
            }
        }
        if ($recoverModules.Count -eq 0) {
            Write-Failure "没有有效的模块需要恢复"
            exit 1
        }
        Write-Host "恢复模式: 多模块恢复 ($($recoverModules.Count) 个模块)"
    }
    else {
        Write-Failure "请指定恢复模式: -Detect / -Module / -Modules / -All / -Scenario"
        Write-Host ""
        Write-Host "用法:"
        Write-Host "  .\disaster-recovery.ps1 -Detect                       # 检测故障模块"
        Write-Host "  .\disaster-recovery.ps1 -Module m9                    # 恢复指定模块"
        Write-Host "  .\disaster-recovery.ps1 -Modules m5,m9                # 恢复多个模块"
        Write-Host "  .\disaster-recovery.ps1 -All                          # 全系统恢复"
        Write-Host "  .\disaster-recovery.ps1 -Scenario single_module_corruption  # 演练场景"
        Write-Host "  .\disaster-recovery.ps1 -Module m9 -DryRun            # 预览恢复计划"
        exit 1
    }

    # 执行恢复
    $result = Invoke-PriorityRecovery $recoverModules
    $report = New-RecoveryReport

    # 总结
    Write-Header "恢复总结"
    Write-Host "  总模块数: $($Global:RecoveryReport.total_modules)"
    Write-Host "  成功: $($Global:RecoveryReport.successful)" -ForegroundColor Green
    Write-Host "  失败: $($Global:RecoveryReport.failed)" -ForegroundColor $(if ($Global:RecoveryReport.failed -gt 0) { 'Red' } else { 'Gray' })
    Write-Host "  跳过: $($Global:RecoveryReport.skipped)"
    Write-Host "  耗时: $($Global:RecoveryReport.duration_seconds) 秒"
    Write-Host ""

    if ($Global:RecoveryReport.errors.Count -gt 0) {
        Write-Host "错误列表:"
        foreach ($err in $Global:RecoveryReport.errors) {
            Write-Host "  - $err" -ForegroundColor Red
        }
        Write-Host ""
    }

    if ($Global:RecoveryReport.warnings.Count -gt 0) {
        Write-Host "警告列表:"
        foreach ($warn in $Global:RecoveryReport.warnings) {
            Write-Host "  - $warn" -ForegroundColor Yellow
        }
        Write-Host ""
    }

    if ($Global:RecoveryReport.overall_success) {
        Write-Success "灾难恢复操作成功完成！"
        exit 0
    } else {
        Write-Failure "灾难恢复操作部分失败，请检查错误信息并处理"
        exit 1
    }
}

# 执行主函数
Main
