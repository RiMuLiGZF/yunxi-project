<#
.SYNOPSIS
    云汐系统 - 生产环境升级脚本
.DESCRIPTION
    安全升级生产环境，包括：
    - 升级前全量备份
    - Git 拉取最新代码
    - 依赖更新
    - 数据库迁移
    - 滚动重启（逐个模块重启，不中断服务）
    - 健康检查验证
    - 失败自动回滚
.PARAMETER ConfigFile
    配置文件路径
.PARAMETER BackupDir
    备份目录，默认 backup/
.PARAMETER TargetCommit
    升级到指定 commit，默认拉取最新
.PARAMETER Branch
    指定分支，默认当前分支
.PARAMETER SkipBackup
    跳过备份（不推荐）
.PARAMETER SkipRollback
    失败时不自动回滚（用于调试）
.PARAMETER DryRun
    试运行模式
.EXAMPLE
    .\upgrade.ps1 -DryRun
    试运行升级流程
.EXAMPLE
    .\upgrade.ps1 -TargetCommit abc1234
    升级到指定 commit
.EXAMPLE
    .\upgrade.ps1 -Branch main
    切换到 main 分支并升级
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ConfigFile = "",
    [string]$BackupDir = "",
    [string]$TargetCommit = "",
    [string]$Branch = "",
    [switch]$SkipBackup,
    [switch]$SkipRollback,
    [switch]$DryRun
)

# ============================================================
# 初始化
# ============================================================

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = Get-Location }

$Script:UpgradeStartTime = Get-Date
$Script:UpgradeSteps = @()
$Script:UpgradeErrors = @()
$Script:UpgradeWarnings = @()
$Script:OriginalCommit = ""
$Script:BackupPath = ""
$Script:RollbackNeeded = $false

# 模块定义（按启动顺序反向排列，用于滚动重启）
$Modules = @(
    @{Name = "Gateway";        Dir = "API-Gateway";            Port = 8080; Order = 1; Command = "python server.py" },
    @{Name = "M5 TideMemory";  Dir = "M5-tide-memory";         Port = 8005; Order = 1; Command = "python server.py" },
    @{Name = "M11 MCP Bus";    Dir = "M11-mcp-bus";            Port = 8011; Order = 1; Command = "python server.py" },
    @{Name = "M12 Security";   Dir = "M12-security-shield";    Port = 8012; Order = 1; Command = "python server.py" },
    @{Name = "M1 AgentHub";    Dir = "M1-agent-hub";           Port = 8001; Order = 2; Command = "python server.py" },
    @{Name = "M4 SceneEngine"; Dir = "m4-scene-engine";        Port = 8004; Order = 2; Command = "python -m src" },
    @{Name = "M8 ControlTower";Dir = "M8-control-tower";       Port = 8008; Order = 2; Command = "python -m backend" },
    @{Name = "M2 SkillCluster";Dir = "M2-skills-cluster";      Port = 8002; Order = 3; Command = "python start_server.py" },
    @{Name = "M3 EdgeCloud";   Dir = "M3-edge-cloud";          Port = 8003; Order = 3; Command = "python server.py" },
    @{Name = "M6 Hardware";    Dir = "M6-hardware-peripheral"; Port = 8006; Order = 3; Command = "python server.py" },
    @{Name = "M7 Workflow";    Dir = "M7-workflow-builder";    Port = 8007; Order = 3; Command = "python server.py" },
    @{Name = "M9 DevWorkshop"; Dir = "M9-dev-workshop";        Port = 8009; Order = 3; Command = "python backend/main.py" },
    @{Name = "M10 SystemGuard";Dir = "M10-system-guard";       Port = 8010; Order = 3; Command = "python server.py" },
    @{Name = "M0 Console";     Dir = "M0-principal-console";   Port = 8000; Order = 4; Command = "python server.py" }
)

# ============================================================
# 工具函数
# ============================================================

function Write-StepHeader {
    param([string]$Message)
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  $Message" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Success { param([string]$M)
    Write-Host "[OK] " -ForegroundColor Green -NoNewline; Write-Host $M }
function Write-Failure { param([string]$M)
    Write-Host "[FAIL] " -ForegroundColor Red -NoNewline; Write-Host $M
    $Script:UpgradeErrors += $M }
function Write-Warning { param([string]$M)
    Write-Host "[WARN] " -ForegroundColor Yellow -NoNewline; Write-Host $M
    $Script:UpgradeWarnings += $M }
function Write-Info { param([string]$M)
    Write-Host "[INFO] " -ForegroundColor Gray -NoNewline; Write-Host $M }

function Add-UpgradeStep {
    param([string]$Name, [string]$Status, [string]$Detail = "")
    $Script:UpgradeSteps += [PSCustomObject]@{
        Name   = $Name
        Status = $Status
        Detail = $Detail
        Time   = Get-Date
    }
}

function Invoke-CheckDryRun {
    param([string]$Action)
    if ($DryRun) {
        Write-Host "[DRY-RUN] " -ForegroundColor Magenta -NoNewline
        Write-Host $Action
        return $true
    }
    return $false
}

# ============================================================
# 步骤 1: 升级前检查
# ============================================================

function Test-PreUpgrade {
    Write-StepHeader "步骤 1/7: 升级前检查"

    $allPassed = $true

    # 检查 Git 是否可用
    Write-Info "检查 Git..."
    try {
        $null = git --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Git 可用"
        }
        else {
            Write-Failure "Git 不可用"
            $allPassed = $false
        }
    }
    catch {
        Write-Failure "Git 检查失败: $($_.Exception.Message)"
        $allPassed = $false
    }

    # 检查是否在 Git 仓库中
    if ($allPassed) {
        try {
            Push-Location $ProjectRoot
            $null = git rev-parse --is-inside-work-tree 2>&1
            if ($LASTEXITCODE -ne 0) {
                Write-Failure "当前目录不是 Git 仓库"
                $allPassed = $false
            }
            else {
                Write-Success "Git 仓库确认"
            }
            Pop-Location
        }
        catch {
            Pop-Location
            Write-Failure "Git 仓库检查失败: $($_.Exception.Message)"
            $allPassed = $false
        }
    }

    # 保存当前 commit
    if ($allPassed) {
        try {
            Push-Location $ProjectRoot
            $Script:OriginalCommit = git rev-parse HEAD 2>&1
            $currentBranch = git rev-parse --abbrev-ref HEAD 2>&1
            Pop-Location
            Write-Info "当前版本: $($Script:OriginalCommit.Substring(0, 8))"
            Write-Info "当前分支: $currentBranch"
        }
        catch {
            Pop-Location
            Write-Warning "无法获取当前版本信息"
        }
    }

    # 检查工作区是否干净
    if ($allPassed) {
        try {
            Push-Location $ProjectRoot
            $status = git status --porcelain 2>&1
            Pop-Location
            if ($status -and $status.Count -gt 0) {
                Write-Warning "工作区有未提交的更改: $($status.Count) 个文件"
                Write-Info "建议先提交或暂存更改后再升级"
            }
            else {
                Write-Success "工作区干净"
            }
        }
        catch {
            Pop-Location
            Write-Warning "无法检查工作区状态"
        }
    }

    # 检查 Python
    Write-Info "检查 Python..."
    try {
        $null = python --version 2>&1
        Write-Success "Python 可用"
    }
    catch {
        Write-Warning "Python 检查失败"
    }

    Add-UpgradeStep -Name "升级前检查" -Status $(if ($allPassed) { "PASS" } else { "FAIL" })
    return $allPassed
}

# ============================================================
# 步骤 2: 全量备份
# ============================================================

function Invoke-Backup {
    Write-StepHeader "步骤 2/7: 升级前备份"

    if ($SkipBackup) {
        Write-Warning "已跳过备份（不推荐）"
        Add-UpgradeStep -Name "全量备份" -Status "SKIP"
        return $true
    }

    if (Invoke-CheckDryRun "将创建升级前备份") {
        Add-UpgradeStep -Name "全量备份" -Status "DRY-RUN"
        return $true
    }

    try {
        # 确定备份目录
        if ([string]::IsNullOrEmpty($BackupDir)) {
            $BackupDir = Join-Path $ProjectRoot "backup"
        }

        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $backupName = "yunxi_backup_$timestamp"
        $Script:BackupPath = Join-Path $BackupDir $backupName

        Write-Info "备份目录: $($Script:BackupPath)"

        # 创建备份目录
        if (-not (Test-Path $Script:BackupPath)) {
            New-Item -ItemType Directory -Path $Script:BackupPath -Force | Out-Null
        }

        # 1. 备份代码（Git commit hash + 工作区差异）
        Write-Info "备份代码版本信息..."
        Push-Location $ProjectRoot
        git rev-parse HEAD | Out-File (Join-Path $Script:BackupPath "git-commit.txt") -Encoding UTF8
        git status --porcelain | Out-File (Join-Path $Script:BackupPath "git-status.txt") -Encoding UTF8
        git diff | Out-File (Join-Path $Script:BackupPath "git-diff.patch") -Encoding UTF8
        Pop-Location

        # 2. 备份配置文件
        Write-Info "备份配置文件..."
        $configDir = Join-Path $ProjectRoot "config"
        $backupConfigDir = Join-Path $Script:BackupPath "config"
        if (Test-Path $configDir) {
            Copy-Item $configDir $backupConfigDir -Recurse -Force
        }

        # 3. 备份数据目录
        Write-Info "备份数据目录..."
        $dataDir = Join-Path $ProjectRoot "data"
        $backupDataDir = Join-Path $Script:BackupPath "data"
        if (Test-Path $dataDir) {
            Copy-Item $dataDir $backupDataDir -Recurse -Force
        }

        # 4. 备份版本信息
        $versionInfo = @{
            BackupTime   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            OriginalCommit = $Script:OriginalCommit
            ProjectRoot  = $ProjectRoot
            Modules      = $Modules.Count
        }
        $versionInfo | ConvertTo-Json | Out-File (Join-Path $Script:BackupPath "backup-info.json") -Encoding UTF8

        Write-Success "备份完成: $($Script:BackupPath)"

        # 计算备份大小
        $backupSize = (Get-ChildItem $Script:BackupPath -Recurse | Measure-Object -Property Length -Sum).Sum
        $backupSizeMB = [math]::Round($backupSize / 1MB, 2)
        Write-Info "备份大小: ${backupSizeMB} MB"

        Add-UpgradeStep -Name "全量备份" -Status "DONE" -Detail "$backupName (${backupSizeMB}MB)"
        return $true
    }
    catch {
        Write-Failure "备份失败: $($_.Exception.Message)"
        Add-UpgradeStep -Name "全量备份" -Status "FAIL" -Detail $_.Exception.Message
        return $false
    }
}

# ============================================================
# 步骤 3: 拉取最新代码
# ============================================================

function Invoke-GitPull {
    Write-StepHeader "步骤 3/7: 拉取最新代码"

    if (Invoke-CheckDryRun "将拉取最新代码") {
        Add-UpgradeStep -Name "代码更新" -Status "DRY-RUN"
        return $true
    }

    try {
        Push-Location $ProjectRoot

        # 切换分支（如果指定）
        if (-not [string]::IsNullOrEmpty($Branch)) {
            Write-Info "切换到分支: $Branch..."
            git checkout $Branch 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Failure "切换分支失败: $Branch"
                Pop-Location
                Add-UpgradeStep -Name "代码更新" -Status "FAIL" -Detail "分支切换失败"
                return $false
            }
            Write-Success "已切换到分支: $Branch"
        }

        # 拉取最新代码
        if (-not [string]::IsNullOrEmpty($TargetCommit)) {
            Write-Info "切换到指定 commit: $TargetCommit..."
            git checkout $TargetCommit 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Failure "切换到指定 commit 失败"
                Pop-Location
                Add-UpgradeStep -Name "代码更新" -Status "FAIL" -Detail "commit 切换失败"
                return $false
            }
            $newCommit = $TargetCommit
        }
        else {
            Write-Info "拉取最新代码..."
            git pull 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Failure "Git pull 失败"
                Pop-Location
                Add-UpgradeStep -Name "代码更新" -Status "FAIL" -Detail "git pull 失败"
                return $false
            }
            $newCommit = git rev-parse HEAD 2>&1
        }

        Pop-Location

        if ($newCommit -eq $Script:OriginalCommit) {
            Write-Info "已是最新版本，无需更新"
            Add-UpgradeStep -Name "代码更新" -Status "SKIP" -Detail "已是最新"
            return $true
        }

        Write-Success "代码已更新: $($Script:OriginalCommit.Substring(0,8)) -> $($newCommit.Substring(0,8))"

        # 显示变更摘要
        try {
            Push-Location $ProjectRoot
            $changeCount = git diff --stat $Script:OriginalCommit HEAD 2>&1
            Pop-Location
            if ($changeCount) {
                Write-Info "变更摘要:"
                $changeCount | Select-Object -Last 5 | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }
            }
        }
        catch { Pop-Location }

        Add-UpgradeStep -Name "代码更新" -Status "DONE" -Detail "更新到 $($newCommit.Substring(0,8))"
        return $true
    }
    catch {
        Pop-Location
        Write-Failure "代码更新失败: $($_.Exception.Message)"
        Add-UpgradeStep -Name "代码更新" -Status "FAIL" -Detail $_.Exception.Message
        return $false
    }
}

# ============================================================
# 步骤 4: 依赖更新
# ============================================================

function Update-Dependencies {
    Write-StepHeader "步骤 4/7: 依赖更新"

    if (Invoke-CheckDryRun "将更新 Python 依赖") {
        Add-UpgradeStep -Name "依赖更新" -Status "DRY-RUN"
        return $true
    }

    $successCount = 0
    $failCount = 0

    # 更新 shared 依赖
    $sharedReq = Join-Path $ProjectRoot "shared\requirements.txt"
    if (Test-Path $sharedReq) {
        Write-Info "更新 shared 依赖..."
        try {
            pip install --upgrade -r $sharedReq 2>&1 | Out-Null
            Write-Success "shared 依赖更新完成"
            $successCount++
        }
        catch {
            Write-Failure "shared 依赖更新失败: $($_.Exception.Message)"
            $failCount++
        }
    }

    # 更新各模块依赖
    foreach ($mod in $Modules) {
        $modDir = Join-Path $ProjectRoot $mod.Dir
        $reqFile = Join-Path $modDir "requirements.txt"

        if (-not (Test-Path $reqFile)) {
            $reqFile = Join-Path $modDir "backend\requirements.txt"
        }

        if (Test-Path $reqFile) {
            Write-Info "更新 $($mod.Name) 依赖..."
            try {
                pip install --upgrade -r $reqFile 2>&1 | Out-Null
                Write-Success "$($mod.Name) 依赖更新完成"
                $successCount++
            }
            catch {
                Write-Warning "$($mod.Name) 依赖更新失败: $($_.Exception.Message)"
                $failCount++
            }
        }
    }

    Add-UpgradeStep -Name "依赖更新" -Status $(if ($failCount -eq 0) { "DONE" } else { "WARN" }) `
        -Detail "成功: $successCount, 失败: $failCount"

    return ($failCount -eq 0)
}

# ============================================================
# 步骤 5: 数据库迁移
# ============================================================

function Invoke-DbMigration {
    Write-StepHeader "步骤 5/7: 数据库迁移"

    if (Invoke-CheckDryRun "将执行数据库迁移") {
        Add-UpgradeStep -Name "数据库迁移" -Status "DRY-RUN"
        return $true
    }

    $migratedCount = 0
    $failedCount = 0

    foreach ($mod in $Modules) {
        $modDir = Join-Path $ProjectRoot $mod.Dir

        # 查找迁移脚本
        $migrationScripts = @(
            "migrate.py",
            "alembic\upgrade.py",
            "db_migrate.py"
        )

        $foundScript = $null
        foreach ($script in $migrationScripts) {
            $scriptPath = Join-Path $modDir $script
            if (Test-Path $scriptPath) {
                $foundScript = $scriptPath
                break
            }
        }

        if ($foundScript) {
            Write-Info "执行 $($mod.Name) 数据库迁移..."
            try {
                Push-Location $modDir
                python (Split-Path $foundScript -Leaf) 2>&1 | Out-Null
                Pop-Location
                Write-Success "$($mod.Name) 数据库迁移完成"
                $migratedCount++
            }
            catch {
                Pop-Location
                Write-Warning "$($mod.Name) 数据库迁移失败: $($_.Exception.Message)"
                $failedCount++
            }
        }
    }

    if ($migratedCount -eq 0) {
        Write-Info "未找到需要迁移的数据库"
    }

    Add-UpgradeStep -Name "数据库迁移" -Status "DONE" -Detail "迁移: $migratedCount, 失败: $failedCount"
    return ($failedCount -eq 0)
}

# ============================================================
# 步骤 6: 滚动重启
# ============================================================

function Invoke-RollingRestart {
    Write-StepHeader "步骤 6/7: 滚动重启服务"

    if (Invoke-CheckDryRun "将执行滚动重启") {
        Add-UpgradeStep -Name "滚动重启" -Status "DRY-RUN"
        return $true
    }

    # 加载配置
    $envFile = if ($ConfigFile) { $ConfigFile } else { Join-Path $ProjectRoot "config\yunxi.env.prod" }
    if (-not (Test-Path $envFile)) {
        $envFile = Join-Path $ProjectRoot "config\yunxi.env"
    }
    if (Test-Path $envFile) {
        Write-Info "加载配置: $envFile"
        Get-Content $envFile -Encoding UTF8 | ForEach-Object {
            $line = $_.Trim()
            if ($line -and !$line.StartsWith("#") -and $line -match "^([A-Za-z_0-9]+)=(.*)$") {
                $key = $Matches[1]
                $val = $Matches[2]
                if ($val.Length -gt 0) {
                    [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
                }
            }
        }
    }

    $restartedCount = 0
    $failedCount = 0
    $newPids = @{}

    # 按反向顺序逐个重启（先重启非核心模块，最后重启网关）
    $sortedModules = $Modules | Sort-Object { $_.Order } -Descending

    foreach ($mod in $sortedModules) {
        $modDir = Join-Path $ProjectRoot $mod.Dir

        if (-not (Test-Path $modDir)) {
            Write-Warning "跳过 $($mod.Name) (目录不存在)"
            continue
        }

        Write-Info "重启 $($mod.Name) (端口: $($mod.Port))..."

        # 1. 停止旧进程
        try {
            $conn = Get-NetTCPConnection -LocalPort $mod.Port -State Listen -ErrorAction SilentlyContinue
            if ($conn) {
                foreach ($c in $conn) {
                    try {
                        Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop
                        Write-Info "  停止旧进程 PID: $($c.OwningProcess)"
                    }
                    catch {
                        Write-Warning "  停止进程 PID $($c.OwningProcess) 失败"
                    }
                }
                Start-Sleep -Seconds 2
            }
        }
        catch {}

        # 2. 启动新进程
        try {
            $proc = Start-Process -FilePath "python" `
                -ArgumentList $mod.Command `
                -WorkingDirectory $modDir `
                -WindowStyle Minimized `
                -PassThru `
                -ErrorAction Stop

            if ($proc) {
                $newPids[$mod.Dir] = $proc.Id
                Write-Info "  新进程 PID: $($proc.Id)"

                # 3. 等待健康检查通过
                $healthTimeout = 30
                $healthy = $false
                $deadline = (Get-Date).AddSeconds($healthTimeout)

                while ((Get-Date) -lt $deadline -and -not $healthy) {
                    try {
                        $response = Invoke-RestMethod -Uri "http://localhost:$($mod.Port)/health" -TimeoutSec 3 -ErrorAction Stop
                        if ($response.status -eq "ok" -or $response.status -eq "healthy" -or $response.code -eq 0) {
                            $healthy = $true
                        }
                    }
                    catch {}
                    if (-not $healthy) { Start-Sleep -Seconds 2 }
                }

                if ($healthy) {
                    Write-Success "$($mod.Name) 重启成功并通过健康检查"
                    $restartedCount++
                }
                else {
                    Write-Warning "$($mod.Name) 已启动但健康检查超时"
                    $restartedCount++
                }
            }
            else {
                Write-Failure "$($mod.Name) 启动失败"
                $failedCount++
            }
        }
        catch {
            Write-Failure "$($mod.Name) 重启异常: $($_.Exception.Message)"
            $failedCount++
        }
    }

    # 保存新的 PID 文件
    if ($newPids.Count -gt 0) {
        $pidFile = Join-Path $ProjectRoot ".deploy-prod-pids.json"
        $newPids | ConvertTo-Json | Set-Content $pidFile -Encoding UTF8
    }

    Add-UpgradeStep -Name "滚动重启" -Status $(if ($failedCount -eq 0) { "DONE" } else { "WARN" }) `
        -Detail "成功: $restartedCount, 失败: $failedCount"

    return ($failedCount -eq 0)
}

# ============================================================
# 步骤 7: 健康检查验证
# ============================================================

function Invoke-HealthVerification {
    Write-StepHeader "步骤 7/7: 健康检查验证"

    if (Invoke-CheckDryRun "将执行健康检查验证") {
        Add-UpgradeStep -Name "健康验证" -Status "DRY-RUN"
        return $true
    }

    $healthyCount = 0
    $unhealthyCount = 0

    foreach ($mod in $Modules) {
        $healthUrl = "http://localhost:$($mod.Port)/health"

        try {
            $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 5 -ErrorAction Stop
            $isHealthy = $response.status -eq "ok" -or $response.status -eq "healthy" -or $response.code -eq 0

            if ($isHealthy) {
                Write-Success "$($mod.Name) 健康"
                $healthyCount++
            }
            else {
                Write-Warning "$($mod.Name) 状态异常"
                $unhealthyCount++
            }
        }
        catch {
            Write-Failure "$($mod.Name) 健康检查失败: $($_.Exception.Message)"
            $unhealthyCount++
        }
    }

    Add-UpgradeStep -Name "健康验证" -Status $(if ($unhealthyCount -eq 0) { "PASS" } else { "FAIL" }) `
        -Detail "健康: $healthyCount/$($Modules.Count)"

    return ($unhealthyCount -eq 0)
}

# ============================================================
# 回滚流程
# ============================================================

function Invoke-Rollback {
    Write-StepHeader "执行回滚..."

    if ($SkipRollback) {
        Write-Warning "已跳过自动回滚"
        return
    }

    if ([string]::IsNullOrEmpty($Script:BackupPath)) {
        Write-Failure "无可用备份，无法回滚"
        return
    }

    Write-Warning "升级失败，开始自动回滚..."
    Write-Info "回滚到版本: $($Script:OriginalCommit.Substring(0, 8))"
    Write-Info "备份位置: $($Script:BackupPath)"

    try {
        # 1. 恢复代码
        Write-Info "恢复代码版本..."
        Push-Location $ProjectRoot
        git checkout $Script:OriginalCommit 2>&1 | Out-Null
        Pop-Location
        Write-Success "代码已回滚到 $($Script:OriginalCommit.Substring(0, 8))"

        # 2. 恢复配置
        Write-Info "恢复配置文件..."
        $backupConfigDir = Join-Path $Script:BackupPath "config"
        $configDir = Join-Path $ProjectRoot "config"
        if (Test-Path $backupConfigDir) {
            Copy-Item "$backupConfigDir\*" $configDir -Recurse -Force
            Write-Success "配置文件已恢复"
        }

        # 3. 恢复数据
        Write-Info "恢复数据目录..."
        $backupDataDir = Join-Path $Script:BackupPath "data"
        $dataDir = Join-Path $ProjectRoot "data"
        if (Test-Path $backupDataDir) {
            if (Test-Path $dataDir) {
                Remove-Item $dataDir -Recurse -Force
            }
            Copy-Item $backupDataDir $dataDir -Recurse -Force
            Write-Success "数据已恢复"
        }

        # 4. 重启服务
        Write-Info "重启服务..."
        & (Join-Path $ProjectRoot "stop-all.ps1") 2>&1 | Out-Null
        Start-Sleep -Seconds 3

        $envFile = Join-Path $ProjectRoot "config\yunxi.env"
        if (Test-Path $envFile) {
            Get-Content $envFile -Encoding UTF8 | ForEach-Object {
                $line = $_.Trim()
                if ($line -and !$line.StartsWith("#") -and $line -match "^([A-Za-z_0-9]+)=(.*)$") {
                    $key = $Matches[1]
                    $val = $Matches[2]
                    if ($val.Length -gt 0) {
                        [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
                    }
                }
            }
        }

        $startedPids = @{}
        foreach ($mod in ($Modules | Sort-Object { $_.Order })) {
            $modDir = Join-Path $ProjectRoot $mod.Dir
            if (Test-Path $modDir) {
                try {
                    $proc = Start-Process -FilePath "python" `
                        -ArgumentList $mod.Command `
                        -WorkingDirectory $modDir `
                        -WindowStyle Minimized `
                        -PassThru `
                        -ErrorAction SilentlyContinue
                    if ($proc) { $startedPids[$mod.Dir] = $proc.Id }
                }
                catch {}
                Start-Sleep -Milliseconds 500
            }
        }

        $pidFile = Join-Path $ProjectRoot ".deploy-prod-pids.json"
        $startedPids | ConvertTo-Json | Set-Content $pidFile -Encoding UTF8

        Write-Success "回滚完成，服务已重启"
    }
    catch {
        Write-Failure "回滚失败: $($_.Exception.Message)"
        Write-Warning "请手动执行回滚: .\rollback.ps1 -BackupPath $($Script:BackupPath)"
    }
}

# ============================================================
# 升级报告
# ============================================================

function Show-UpgradeReport {
    Write-StepHeader "升级结果报告"

    $endTime = Get-Date
    $duration = ($endTime - $Script:UpgradeStartTime).TotalSeconds

    Write-Host "升级时间: $($Script:UpgradeStartTime.ToString('yyyy-MM-dd HH:mm:ss')) -> $($endTime.ToString('yyyy-MM-dd HH:mm:ss'))"
    Write-Host "总耗时: $([math]::Round($duration, 2)) 秒"
    Write-Host "原始版本: $($Script:OriginalCommit.Substring(0, 8))"
    if ($Script:BackupPath) {
        Write-Host "备份位置: $($Script:BackupPath)"
    }
    Write-Host ""

    Write-Host "步骤详情:" -ForegroundColor Cyan
    Write-Host "--------"
    foreach ($step in $Script:UpgradeSteps) {
        $statusColor = switch ($step.Status) {
            "PASS" { "Green" }
            "DONE" { "Green" }
            "WARN" { "Yellow" }
            "SKIP" { "Gray" }
            "DRY-RUN" { "Magenta" }
            "FAIL" { "Red" }
            default { "White" }
        }
        Write-Host ("  [{0}] {1,-20} {2}" -f $step.Status, $step.Name, $step.Detail) -ForegroundColor $statusColor
    }

    Write-Host ""

    $overallStatus = "SUCCESS"
    $overallColor = "Green"
    if ($Script:UpgradeErrors.Count -gt 0) {
        $overallStatus = "FAILED"
        $overallColor = "Red"
    }
    elseif ($Script:UpgradeWarnings.Count -gt 0) {
        $overallStatus = "PARTIAL"
        $overallColor = "Yellow"
    }

    Write-Host "总体状态: $overallStatus" -ForegroundColor $overallColor
    Write-Host "错误数: $($Script:UpgradeErrors.Count)"
    Write-Host "警告数: $($Script:UpgradeWarnings.Count)"
    Write-Host ""

    if ($Script:BackupPath) {
        Write-Host "如需回滚: .\rollback.ps1 -BackupPath $($Script:BackupPath)" -ForegroundColor Gray
    }
    Write-Host "健康检查: .\scripts\health-check.ps1" -ForegroundColor Gray
    Write-Host ""
}

# ============================================================
# 主流程
# ============================================================

function Main {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor White
    Write-Host "  云汐系统 - 生产环境升级" -ForegroundColor White
    Write-Host "========================================" -ForegroundColor White
    Write-Host ""
    Write-Host "项目根目录: $ProjectRoot"
    if ($DryRun) { Write-Host "模式: DRY-RUN (试运行)" -ForegroundColor Magenta }
    Write-Host ""

    $upgradeSuccess = $true

    # 步骤 1: 升级前检查
    if (-not (Test-PreUpgrade)) {
        Write-Failure "升级前检查未通过，升级终止"
        Show-UpgradeReport
        exit 1
    }

    # 步骤 2: 全量备份
    if (-not (Invoke-Backup)) {
        Write-Failure "备份失败，升级终止"
        Show-UpgradeReport
        exit 1
    }

    # 步骤 3: 拉取最新代码
    if (-not (Invoke-GitPull)) {
        $Script:RollbackNeeded = $true
    }

    # 步骤 4: 依赖更新
    if (-not $Script:RollbackNeeded) {
        Update-Dependencies | Out-Null
    }

    # 步骤 5: 数据库迁移
    if (-not $Script:RollbackNeeded) {
        Invoke-DbMigration | Out-Null
    }

    # 步骤 6: 滚动重启
    if (-not $Script:RollbackNeeded) {
        if (-not (Invoke-RollingRestart)) {
            $Script:RollbackNeeded = $true
        }
    }

    # 步骤 7: 健康检查验证
    if (-not $Script:RollbackNeeded) {
        if (-not (Invoke-HealthVerification)) {
            $Script:RollbackNeeded = $true
        }
    }

    # 失败回滚
    if ($Script:RollbackNeeded -and -not $SkipRollback -and -not $DryRun) {
        Invoke-Rollback
        $upgradeSuccess = $false
    }

    # 升级报告
    Show-UpgradeReport

    if ($upgradeSuccess) {
        exit 0
    }
    else {
        exit 1
    }
}

Main
