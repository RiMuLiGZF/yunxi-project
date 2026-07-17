<#
.SYNOPSIS
云汐系统备份验证脚本 - 第四阶段生产就绪

.DESCRIPTION
验证备份文件的完整性、可恢复性和数据一致性。
支持：
- 验证单个备份文件/目录
- 验证指定模块的所有备份
- 验证全系统备份
- 验证备份可成功恢复（Dry-run 模式）
- 验证恢复后数据一致性
- 输出验证报告（JSON/文本）
- 支持定期自动验证（配合 Windows 任务计划）

使用方式：
  .\verify-backup.ps1 -Module m9
  .\verify-backup.ps1 -BackupDir "C:\path\to\backup"
  .\verify-backup.ps1 -All -ReportPath "C:\reports\verify-report.json"
  .\verify-backup.ps1 -Module m9 -TestRestore -DryRun
  .\verify-backup.ps1 -All -AutoVerify  # 用于定时任务

.NOTES
第四阶段 - 容灾与恢复验证
#>

param(
    [Parameter(Mandatory=$false, HelpMessage="指定模块ID，如 m9、m5")]
    [string]$Module = "",

    [Parameter(Mandatory=$false, HelpMessage="指定备份目录路径")]
    [string]$BackupDir = "",

    [Parameter(Mandatory=$false, HelpMessage="验证所有模块的最新备份")]
    [switch]$All = $false,

    [Parameter(Mandatory=$false, HelpMessage="测试恢复（恢复到临时目录，验证数据一致性）")]
    [switch]$TestRestore = $false,

    [Parameter(Mandatory=$false, HelpMessage="Dry-run 模式，仅检查不执行实际恢复")]
    [switch]$DryRun = $false,

    [Parameter(Mandatory=$false, HelpMessage="验证报告输出路径（JSON格式）")]
    [string]$ReportPath = "",

    [Parameter(Mandatory=$false, HelpMessage="自动验证模式（用于定时任务，输出简洁日志）")]
    [switch]$AutoVerify = $false,

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

# 备份管理器 Python 脚本路径
$BackupPy = Join-Path $ProjectRoot "shared\data\data_layer\backup.py"
$BackupManagerDir = Join-Path $ProjectRoot "shared\data\data_layer"

# 模块备份注册表路径
$ModuleRegistryPy = Join-Path $BackupManagerDir "module_backup_registry.py"

# 验证结果存储
$Global:VerifyResults = @{
    timestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    total_backups = 0
    passed = 0
    failed = 0
    warnings = 0
    modules = @{}
    errors = @()
    duration_seconds = 0
}

$StartTime = Get-Date

# ============================================================
# 输出辅助函数
# ============================================================

function Write-Header($title) {
    if ($AutoVerify) { return }
    $line = "=" * 70
    Write-Host ""
    Write-Host $line -ForegroundColor Cyan
    Write-Host "  $title" -ForegroundColor Cyan
    Write-Host $line -ForegroundColor Cyan
    Write-Host ""
}

function Write-Success($msg) {
    if ($AutoVerify) {
        Write-Host "[PASS] $msg"
    } else {
        Write-Host "[OK] $msg" -ForegroundColor Green
    }
}

function Write-Failure($msg) {
    if ($AutoVerify) {
        Write-Host "[FAIL] $msg"
    } else {
        Write-Host "[FAIL] $msg" -ForegroundColor Red
    }
    $Global:VerifyResults.errors += $msg
}

function Write-WarningMsg($msg) {
    if ($AutoVerify) {
        Write-Host "[WARN] $msg"
    } else {
        Write-Host "[WARN] $msg" -ForegroundColor Yellow
    }
    $Global:VerifyResults.warnings++
}

function Write-Info($msg) {
    if ($AutoVerify) { return }
    Write-Host "       $msg" -ForegroundColor Gray
}

# ============================================================
# Python 环境检测
# ============================================================

function Test-PythonAvailable {
    try {
        $py = & python --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            return $true
        }
    } catch { }
    try {
        $py = & python3 --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            return $true
        }
    } catch { }
    return $false
}

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
# 备份文件检测与验证
# ============================================================

function Get-BackupDirs($moduleId) {
    <#
    获取指定模块的所有备份目录
    #>
    $backupRoot = Join-Path $ProjectRoot "backups" "module_backups" $moduleId
    if (-not (Test-Path $backupRoot)) {
        return @()
    }

    $dirs = Get-ChildItem $backupRoot -Directory | Where-Object {
        $_.Name -match "^${moduleId}_"
    } | Sort-Object CreationTime -Descending

    return $dirs
}

function Test-BackupFileIntegrity($backupFile) {
    <#
    验证单个备份文件的完整性
    返回: @{ valid=$true/false; size=0; checksum=""; details="" }
    #>
    $result = @{
        valid = $false
        file_path = $backupFile
        file_name = (Split-Path $backupFile -Leaf)
        size_bytes = 0
        sha256 = ""
        errors = @()
    }

    if (-not (Test-Path $backupFile -PathType Leaf)) {
        $result.errors += "文件不存在: $backupFile"
        return $result
    }

    $fileInfo = Get-Item $backupFile
    $result.size_bytes = $fileInfo.Length

    if ($fileInfo.Length -eq 0) {
        $result.errors += "文件大小为0"
        return $result
    }

    # 计算 SHA-256 校验和
    try {
        $sha = Get-FileHash $backupFile -Algorithm SHA256
        $result.sha256 = $sha.Hash.ToLower()
    } catch {
        $result.errors += "计算校验和失败: $($_.Exception.Message)"
        return $result
    }

    # 检查文件扩展名，判断备份类型
    $ext = $fileInfo.Extension.ToLower()
    $fileName = $fileInfo.Name.ToLower()

    # 检查元数据文件是否存在
    $metaFile = "$backupFile.meta.json"
    $metaValid = $false
    $metaChecksum = ""

    if (Test-Path $metaFile) {
        try {
            $meta = Get-Content $metaFile -Raw | ConvertFrom-Json
            $metaChecksum = $meta.sha256
            $metaValid = $true
        } catch {
            $result.errors += "元数据文件解析失败: $($_.Exception.Message)"
        }
    }

    # 对于 .db 文件，直接验证 SQLite 完整性
    if ($ext -eq ".db" -or $ext -eq ".sqlite") {
        try {
            $pythonCmd = Get-PythonCmd
            $script = @"
import sqlite3, sys
try:
    conn = sqlite3.connect(r'$backupFile')
    cursor = conn.execute('PRAGMA integrity_check')
    result = cursor.fetchone()[0]
    cursor = conn.execute('SELECT count(*) FROM sqlite_master WHERE type=\"table\"')
    table_count = cursor.fetchone()[0]
    conn.close()
    print(f'OK|{result}|tables={table_count}')
except Exception as e:
    print(f'ERROR|{e}')
"@
            $output = & $pythonCmd -c $script 2>&1
            if ($output -match "^OK\|(.+)\|tables=(\d+)") {
                $integrity = $Matches[1]
                $tableCount = [int]$Matches[2]
                if ($integrity -eq "ok" -and $tableCount -gt 0) {
                    $result.valid = $true
                    $result.details = "integrity=ok, tables=$tableCount"
                } else {
                    $result.errors += "SQLite 完整性检查失败: $integrity, 表数量: $tableCount"
                }
            } else {
                $result.errors += "SQLite 验证执行失败: $output"
            }
        } catch {
            $result.errors += "SQLite 验证异常: $($_.Exception.Message)"
        }
    }
    # .gz 压缩文件
    elseif ($ext -eq ".gz") {
        try {
            # 检查 gzip 文件头部有效性
            $bytes = [System.IO.File]::ReadAllBytes($backupFile)
            if ($bytes.Length -ge 2 -and $bytes[0] -eq 0x1f -and $bytes[1] -eq 0x8b) {
                # 使用 Python 验证 gzip 内容
                $pythonCmd = Get-PythonCmd
                $script = @"
import gzip, sqlite3, tempfile, os, sys
try:
    with gzip.open(r'$backupFile', 'rb') as f:
        data = f.read(100)
    if len(data) >= 16:
        # 尝试完整解压到临时文件并验证
        tmp = tempfile.mktemp(suffix='.db')
        try:
            with gzip.open(r'$backupFile', 'rb') as f_in:
                with open(tmp, 'wb') as f_out:
                    f_out.write(f_in.read())
            conn = sqlite3.connect(tmp)
            cursor = conn.execute('PRAGMA quick_check')
            result = cursor.fetchone()[0]
            cursor = conn.execute('SELECT count(*) FROM sqlite_master WHERE type=\"table\"')
            table_count = cursor.fetchone()[0]
            conn.close()
            print(f'OK|{result}|tables={table_count}')
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    else:
        print('ERROR|empty content')
except Exception as e:
    print(f'ERROR|{e}')
"@
                $output = & $pythonCmd -c $script 2>&1
                if ($output -match "^OK\|(.+)\|tables=(\d+)") {
                    $result.valid = $true
                    $result.details = "gzip_valid, integrity=$($Matches[1]), tables=$($Matches[2])"
                } else {
                    $result.errors += "Gzip 内容验证失败: $output"
                }
            } else {
                $result.errors += "无效的 gzip 文件头"
            }
        } catch {
            $result.errors += "Gzip 验证异常: $($_.Exception.Message)"
        }
    }
    # .enc 加密文件（只验证文件结构，不验证内容）
    elseif ($ext -eq ".enc") {
        if ($fileInfo.Length -gt 28) {  # 12 nonce + 至少数据 + 16 tag
            $result.valid = $true
            $result.details = "encrypted_file (size: $($fileInfo.Length) bytes, structure valid)"
        } else {
            $result.errors += "加密文件过小，可能损坏"
        }
    }
    # .meta.json 文件
    elseif ($fileName -like "*.meta.json") {
        try {
            $meta = Get-Content $backupFile -Raw | ConvertFrom-Json
            if ($meta.sha256 -and $meta.original_size_bytes) {
                $result.valid = $true
                $result.details = "metadata file valid"
            } else {
                $result.errors += "元数据字段不完整"
            }
        } catch {
            $result.errors += "元数据文件解析失败"
        }
    }
    # backup_manifest.json
    elseif ($fileName -eq "backup_manifest.json") {
        try {
            $manifest = Get-Content $backupFile -Raw | ConvertFrom-Json
            if ($manifest.module_id -and $manifest.total_dbs) {
                $result.valid = $true
                $result.details = "manifest: $($manifest.module_id), $($manifest.total_dbs) dbs"
            } else {
                $result.errors += "清单文件字段不完整"
            }
        } catch {
            $result.errors += "清单文件解析失败"
        }
    }
    else {
        # 其他文件：只要有大小和校验和就算通过
        $result.valid = $true
        $result.details = "file_valid (size: $($fileInfo.Length) bytes)"
    }

    # 元数据校验和比对（如果有）
    if ($metaValid -and $metaChecksum -and $result.sha256 -and $ext -ne ".gz" -and $ext -ne ".enc") {
        if ($metaChecksum -ne $result.sha256) {
            $result.errors += "校验和不匹配: 元数据=$metaChecksum, 实际=$($result.sha256)"
            $result.valid = $false
        }
    }

    return $result
}

function Test-BackupDir($backupDirPath, $moduleId = "") {
    <#
    验证整个备份目录
    返回: @{ valid=$true/false; backup_name=""; files=@(); errors=@() }
    #>
    $result = @{
        valid = $false
        backup_path = $backupDirPath
        backup_name = (Split-Path $backupDirPath -Leaf)
        module_id = $moduleId
        total_files = 0
        valid_files = 0
        db_count = 0
        size_bytes = 0
        file_results = @()
        errors = @()
        has_manifest = $false
    }

    if (-not (Test-Path $backupDirPath -PathType Container)) {
        $result.errors += "备份目录不存在: $backupDirPath"
        return $result
    }

    $files = Get-ChildItem $backupDirPath -File -Recurse
    $result.total_files = $files.Count

    foreach ($file in $files) {
        $fileResult = Test-BackupFileIntegrity $file.FullName
        $result.file_results += $fileResult
        $result.size_bytes += $fileResult.size_bytes

        if ($fileResult.valid) {
            $result.valid_files++
        } else {
            $result.errors += "$($fileResult.file_name): $($fileResult.errors -join '; ')"
        }

        if ($file.Name -eq "backup_manifest.json") {
            $result.has_manifest = $true
        }

        if ($file.Extension -in @(".db", ".gz", ".enc") -and 
            -not $file.Name.EndsWith(".meta.json")) {
            $result.db_count++
        }
    }

    # 判断整体有效性
    $criticalFiles = $files | Where-Object {
        $_.Name -ne "backup_manifest.json" -and 
        -not $_.Name.EndsWith(".meta.json")
    }

    if ($criticalFiles.Count -gt 0 -and $result.valid_files -ge $criticalFiles.Count) {
        $result.valid = $true
    } elseif ($files.Count -eq 0) {
        $result.errors += "备份目录为空"
    }

    return $result
}

# ============================================================
# 恢复测试
# ============================================================

function Test-RestoreBackup($backupDirPath, $moduleId) {
    <#
    测试恢复备份（恢复到临时目录，验证数据一致性）
    #>
    $result = @{
        success = $false
        backup_dir = $backupDirPath
        module_id = $moduleId
        restored_dbs = 0
        total_dbs = 0
        data_integrity = $false
        errors = @()
    }

    if ($DryRun) {
        Write-Info "Dry-run 模式：跳过实际恢复操作"
        $result.success = $true
        $result.details = "dry-run: 恢复操作将执行但未实际执行"
        return $result
    }

    # 创建临时恢复目录
    $tempDir = Join-Path $env:TEMP "yunxi_verify_restore_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    try {
        New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
        Write-Info "临时恢复目录: $tempDir"

        # 获取备份目录中的数据库文件
        $backupDirObj = Get-Item $backupDirPath
        $dbBackupFiles = Get-ChildItem $backupDirPath -File | Where-Object {
            ($_.Extension -in @(".db", ".gz", ".enc")) -and 
            -not $_.Name.EndsWith(".meta.json")
        }

        if ($dbBackupFiles.Count -eq 0) {
            $result.errors += "备份目录中未找到数据库备份文件"
            return $result
        }

        $result.total_dbs = $dbBackupFiles.Count

        # 使用 Python 备份管理器进行恢复测试
        $pythonCmd = Get-PythonCmd

        foreach ($backupFile in $dbBackupFiles) {
            $targetDb = Join-Path $tempDir $backupFile.BaseName
            if ($backupFile.Extension -eq ".gz") {
                $targetDb = $targetDb -replace '\.db$', '.db'
            }

            try {
                $script = @"
import sys, os
sys.path.insert(0, r'$BackupManagerDir')
from backup_manager import BackupManager

bm = BackupManager()
result = bm.restore_backup(
    r'$($backupFile.FullName)',
    r'$targetDb',
    overwrite=True
)
if result.get('success'):
    # 验证恢复后的数据库
    import sqlite3
    conn = sqlite3.connect(r'$targetDb')
    cursor = conn.execute('PRAGMA integrity_check')
    integrity = cursor.fetchone()[0]
    cursor = conn.execute('SELECT count(*) FROM sqlite_master WHERE type=\"table\"')
    tables = cursor.fetchone()[0]
    conn.close()
    print(f'OK|restored_to=$targetDb|integrity={integrity}|tables={tables}')
else:
    print(f'ERROR|{result.get(\"error\", \"unknown\")}')
"@
                $output = & $pythonCmd -c $script 2>&1
                if ($output -match "^OK\|") {
                    $result.restored_dbs++
                    Write-Info "  恢复验证通过: $($backupFile.Name)"
                } else {
                    $result.errors += "$($backupFile.Name): 恢复失败 - $output"
                    Write-WarningMsg "  恢复验证失败: $($backupFile.Name)"
                }
            } catch {
                $result.errors += "$($backupFile.Name): 恢复异常 - $($_.Exception.Message)"
            }
        }

        # 判断数据完整性
        if ($result.restored_dbs -eq $result.total_dbs -and $result.total_dbs -gt 0) {
            $result.data_integrity = $true
            $result.success = $true
        }
    } finally {
        # 清理临时目录
        try {
            if (Test-Path $tempDir) {
                Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
            }
        } catch { }
    }

    return $result
}

# ============================================================
# 模块验证
# ============================================================

function Invoke-ModuleVerification($moduleId) {
    <#
    验证指定模块的备份
    #>
    if ($AutoVerify) {
        Write-Host "[INFO] 验证模块: $moduleId"
    } else {
        Write-Host ""
        Write-Host "--- 模块: $moduleId ---" -ForegroundColor Cyan
    }

    $moduleResult = @{
        module_id = $moduleId
        backup_count = 0
        passed = 0
        failed = 0
        latest_backup = $null
        restore_test = $null
        errors = @()
    }

    $backupDirs = Get-BackupDirs $moduleId
    $moduleResult.backup_count = $backupDirs.Count

    if ($backupDirs.Count -eq 0) {
        Write-WarningMsg "  未找到备份"
        $moduleResult.errors += "未找到备份"
        $Global:VerifyResults.modules[$moduleId] = $moduleResult
        return $moduleResult
    }

    Write-Info "  找到 $($backupDirs.Count) 个备份"

    # 验证最新的备份
    $latest = $backupDirs[0]
    $moduleResult.latest_backup = @{
        name = $latest.Name
        path = $latest.FullName
        created = $latest.CreationTime.ToString("yyyy-MM-dd HH:mm:ss")
    }

    Write-Info "  最新备份: $($latest.Name) ($($latest.CreationTime.ToString('yyyy-MM-dd HH:mm:ss')))"

    $dirResult = Test-BackupDir $latest.FullName $moduleId
    $Global:VerifyResults.total_backups++

    if ($dirResult.valid) {
        Write-Success "  备份完整性验证通过 ($($dirResult.valid_files)/$($dirResult.total_files) 个文件有效)"
        $moduleResult.passed++
        $Global:VerifyResults.passed++
    } else {
        Write-Failure "  备份完整性验证失败: $($dirResult.errors -join '; ')"
        $moduleResult.failed++
        $moduleResult.errors += $dirResult.errors
        $Global:VerifyResults.failed++
    }

    $moduleResult.integrity_check = $dirResult

    # 恢复测试
    if ($TestRestore -and $dirResult.valid) {
        Write-Info "  执行恢复测试..."
        $restoreResult = Test-RestoreBackup $latest.FullName $moduleId
        $moduleResult.restore_test = $restoreResult

        if ($restoreResult.success) {
            Write-Success "  恢复测试通过 ($($restoreResult.restored_dbs)/$($restoreResult.total_dbs) 个数据库恢复成功)"
        } else {
            Write-Failure "  恢复测试失败: $($restoreResult.errors -join '; ')"
            $moduleResult.errors += "恢复测试失败"
            $Global:VerifyResults.failed++
        }
    }

    $Global:VerifyResults.modules[$moduleId] = $moduleResult
    return $moduleResult
}

# ============================================================
# 单备份目录验证
# ============================================================

function Invoke-DirVerification($backupDirPath) {
    <#
    验证指定的备份目录
    #>
    Write-Header "验证备份目录: $backupDirPath"

    $dirResult = Test-BackupDir $backupDirPath
    $Global:VerifyResults.total_backups++

    if ($dirResult.valid) {
        Write-Success "备份完整性验证通过"
        Write-Info "  文件总数: $($dirResult.total_files)"
        Write-Info "  有效文件: $($dirResult.valid_files)"
        Write-Info "  数据库文件: $($dirResult.db_count)"
        Write-Info "  总大小: $([math]::Round($dirResult.size_bytes / 1024 / 1024, 2)) MB"
        Write-Info "  包含清单: $(if ($dirResult.has_manifest) { '是' } else { '否' })"
        $Global:VerifyResults.passed++
    } else {
        Write-Failure "备份完整性验证失败"
        foreach ($err in $dirResult.errors) {
            Write-Host "    - $err" -ForegroundColor Red
        }
        $Global:VerifyResults.failed++
    }

    if ($TestRestore -and $dirResult.valid) {
        Write-Host ""
        Write-Info "执行恢复测试..."
        $restoreResult = Test-RestoreBackup $backupDirPath "custom"
        if ($restoreResult.success) {
            Write-Success "恢复测试通过 ($($restoreResult.restored_dbs)/$($restoreResult.total_dbs) 个数据库恢复成功)"
        } else {
            Write-Failure "恢复测试失败: $($restoreResult.errors -join '; ')"
        }
    }

    $Global:VerifyResults.modules["custom_dir"] = @{
        backup_path = $backupDirPath
        integrity = $dirResult
        restore_test = if ($TestRestore) { $restoreResult } else { $null }
    }
}

# ============================================================
# 报告生成
# ============================================================

function New-VerifyReport {
    <#
    生成验证报告
    #>
    $endTime = Get-Date
    $Global:VerifyResults.duration_seconds = [math]::Round(($endTime - $StartTime).TotalSeconds, 2)
    $Global:VerifyResults.end_time = $endTime.ToString("yyyy-MM-dd HH:mm:ss")

    $Global:VerifyResults.overall_pass = ($Global:VerifyResults.failed -eq 0 -and $Global:VerifyResults.total_backups -gt 0)

    if ($ReportPath) {
        try {
            $reportDir = Split-Path $ReportPath -Parent
            if ($reportDir -and -not (Test-Path $reportDir)) {
                New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
            }
            $Global:VerifyResults | ConvertTo-Json -Depth 10 | Out-File -FilePath $ReportPath -Encoding utf8
            Write-Info "验证报告已保存到: $ReportPath"
        } catch {
            Write-WarningMsg "保存报告失败: $($_.Exception.Message)"
        }
    }

    return $Global:VerifyResults
}

# ============================================================
# 主流程
# ============================================================

function Main {
    if (-not $AutoVerify) {
        Write-Header "云汐系统备份验证工具"
        Write-Info "项目根目录: $ProjectRoot"
        Write-Info "验证时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        Write-Info ""
    }

    # 检查 Python
    if (-not (Test-PythonAvailable)) {
        Write-Failure "未检测到 Python 环境，无法执行完整验证"
        exit 1
    }

    # 检查备份脚本
    if (-not (Test-Path $BackupPy)) {
        Write-Failure "备份管理脚本不存在: $BackupPy"
        exit 1
    }

    # 模式选择
    if ($BackupDir) {
        # 单目录验证模式
        Invoke-DirVerification $BackupDir
    }
    elseif ($Module) {
        # 单模块验证模式
        Invoke-ModuleVerification $Module
    }
    elseif ($All) {
        # 全模块验证模式
        Write-Header "全模块备份验证"

        # 获取所有模块（从注册表）
        $modules = @("m4", "m5", "m6", "m8", "m9", "m10", "m12")

        foreach ($mod in $modules) {
            Invoke-ModuleVerification $mod
        }
    }
    else {
        Write-Failure "请指定 -Module、-BackupDir 或 -All 参数"
        Write-Host ""
        Write-Host "用法:"
        Write-Host "  .\verify-backup.ps1 -Module m9           # 验证 M9 模块备份"
        Write-Host "  .\verify-backup.ps1 -BackupDir <path>    # 验证指定备份目录"
        Write-Host "  .\verify-backup.ps1 -All                 # 验证所有模块"
        Write-Host "  .\verify-backup.ps1 -All -TestRestore    # 验证并测试恢复"
        Write-Host "  .\verify-backup.ps1 -All -AutoVerify     # 自动验证模式（用于定时任务）"
        exit 1
    }

    # 生成报告
    $report = New-VerifyReport

    # 输出总结
    Write-Header "验证总结"
    Write-Host "  总备份数: $($Global:VerifyResults.total_backups)"
    Write-Host "  通过: $($Global:VerifyResults.passed)" -ForegroundColor Green
    Write-Host "  失败: $($Global:VerifyResults.failed)" -ForegroundColor $(if ($Global:VerifyResults.failed -gt 0) { 'Red' } else { 'Gray' })
    Write-Host "  警告: $($Global:VerifyResults.warnings)" -ForegroundColor Yellow
    Write-Host "  耗时: $($Global:VerifyResults.duration_seconds) 秒"
    Write-Host ""

    if ($Global:VerifyResults.overall_pass) {
        Write-Success "所有备份验证通过！"
        exit 0
    } else {
        Write-Failure "部分备份验证未通过，请检查错误信息"
        exit 1
    }
}

# 执行主函数
Main
