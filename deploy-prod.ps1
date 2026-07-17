<#
.SYNOPSIS
    云汐系统 - 生产环境部署脚本
.DESCRIPTION
    一键完成生产环境部署，包括：
    - 环境检查（Python版本、依赖、端口占用、磁盘空间）
    - 配置文件生成（从模板生成 yunxi.env.prod）
    - 依赖安装（生产模式，跳过 dev 依赖）
    - 数据库初始化和迁移
    - 静态资源构建（如果有前端）
    - 服务启动与健康检查
    - 部署结果报告
.PARAMETER ConfigFile
    配置文件路径，默认使用 config/yunxi.env.prod
.PARAMETER SkipEnvCheck
    跳过环境检查
.PARAMETER SkipDependencyInstall
    跳过依赖安装
.PARAMETER SkipDbMigration
    跳过数据库迁移
.PARAMETER SkipFrontendBuild
    跳过前端构建
.PARAMETER DryRun
    试运行模式，仅显示将要执行的操作，不实际执行
.PARAMETER Force
    强制重新部署（即使已有部署）
.EXAMPLE
    .\deploy-prod.ps1 -DryRun
    试运行部署，查看将要执行的操作
.EXAMPLE
    .\deploy-prod.ps1 -ConfigFile .\config\yunxi.env.prod
    使用指定配置文件部署
.EXAMPLE
    .\deploy-prod.ps1 -SkipFrontendBuild
    部署时跳过前端构建
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ConfigFile = "",
    [switch]$SkipEnvCheck,
    [switch]$SkipDependencyInstall,
    [switch]$SkipDbMigration,
    [switch]$SkipFrontendBuild,
    [switch]$Force,
    [switch]$DryRun
)

# ============================================================
# 初始化
# ============================================================

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = Get-Location }

$Script:DeployStartTime = Get-Date
$Script:DeploySteps = @()
$Script:DeployErrors = @()
$Script:DeployWarnings = @()

# 模块定义（与 start-all.ps1 保持一致）
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

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] " -ForegroundColor Green -NoNewline
    Write-Host $Message
}

function Write-Failure {
    param([string]$Message)
    Write-Host "[FAIL] " -ForegroundColor Red -NoNewline
    Write-Host $Message
    $Script:DeployErrors += $Message
}

function Write-Warning {
    param([string]$Message)
    Write-Host "[WARN] " -ForegroundColor Yellow -NoNewline
    Write-Host $Message
    $Script:DeployWarnings += $Message
}

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] " -ForegroundColor Gray -NoNewline
    Write-Host $Message
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

function Add-DeployStep {
    param(
        [string]$Name,
        [string]$Status,
        [string]$Detail = ""
    )
    $Script:DeploySteps += [PSCustomObject]@{
        Name   = $Name
        Status = $Status
        Detail = $Detail
        Time   = Get-Date
    }
}

# ============================================================
# 步骤 1: 环境检查
# ============================================================

function Test-Environment {
    Write-StepHeader "步骤 1/7: 环境检查"

    $allPassed = $true

    # 1.1 Python 版本检查
    Write-Info "检查 Python 版本..."
    try {
        $pythonVersion = python --version 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Failure "Python 未安装或未添加到 PATH"
            $allPassed = $false
        }
        else {
            $versionMatch = [regex]::Match($pythonVersion, "Python (\d+)\.(\d+)\.(\d+)")
            if ($versionMatch.Success) {
                $major = [int]$versionMatch.Groups[1].Value
                $minor = [int]$versionMatch.Groups[2].Value
                if ($major -ge 3 -and $minor -ge 10) {
                    Write-Success "Python 版本: $pythonVersion (满足 >= 3.10)"
                }
                else {
                    Write-Failure "Python 版本过低: $pythonVersion (需要 >= 3.10)"
                    $allPassed = $false
                }
            }
            else {
                Write-Warning "无法解析 Python 版本: $pythonVersion"
            }
        }
    }
    catch {
        Write-Failure "Python 检查失败: $($_.Exception.Message)"
        $allPassed = $false
    }

    # 1.2 pip 检查
    Write-Info "检查 pip..."
    try {
        $null = pip --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Success "pip 可用"
        }
        else {
            Write-Failure "pip 不可用"
            $allPassed = $false
        }
    }
    catch {
        Write-Failure "pip 检查失败: $($_.Exception.Message)"
        $allPassed = $false
    }

    # 1.3 端口占用检查
    Write-Info "检查端口占用..."
    $portConflicts = @()
    foreach ($mod in $Modules) {
        $port = $mod.Port
        $occupied = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if ($occupied) {
            $portConflicts += "$port ($($mod.Name))"
        }
    }
    if ($portConflicts.Count -eq 0) {
        Write-Success "所有端口可用"
    }
    else {
        Write-Warning "以下端口已被占用: $($portConflicts -join ', ')"
        Write-Warning "部署时将跳过已占用端口的模块，或停止现有进程后重试"
    }

    # 1.4 磁盘空间检查
    Write-Info "检查磁盘空间..."
    try {
        $drive = (Get-Item $ProjectRoot).PSDrive
        $freeSpaceGB = [math]::Round($drive.Free / 1GB, 2)
        if ($freeSpaceGB -ge 5) {
            Write-Success "磁盘剩余空间: ${freeSpaceGB} GB (满足 >= 5GB)"
        }
        elseif ($freeSpaceGB -ge 2) {
            Write-Warning "磁盘剩余空间较低: ${freeSpaceGB} GB (建议 >= 5GB)"
        }
        else {
            Write-Failure "磁盘剩余空间不足: ${freeSpaceGB} GB (至少需要 2GB)"
            $allPassed = $false
        }
    }
    catch {
        Write-Warning "无法检查磁盘空间: $($_.Exception.Message)"
    }

    # 1.5 内存检查
    Write-Info "检查内存..."
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $totalMemGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
        $freeMemGB = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
        if ($totalMemGB -ge 8) {
            Write-Success "总内存: ${totalMemGB} GB, 可用: ${freeMemGB} GB"
        }
        elseif ($totalMemGB -ge 4) {
            Write-Warning "内存较低: ${totalMemGB} GB (建议 >= 8GB)"
        }
        else {
            Write-Warning "内存不足: ${totalMemGB} GB (可能影响性能)"
        }
    }
    catch {
        Write-Warning "无法检查内存: $($_.Exception.Message)"
    }

    Add-DeployStep -Name "环境检查" -Status $(if ($allPassed) { "PASS" } else { "FAIL" })

    if (-not $allPassed -and -not $Force) {
        Write-Failure "环境检查未通过，使用 -Force 可强制继续"
        return $false
    }

    return $true
}

# ============================================================
# 步骤 2: 配置文件生成
# ============================================================

function New-ConfigFile {
    Write-StepHeader "步骤 2/7: 配置文件生成"

    if ([string]::IsNullOrEmpty($ConfigFile)) {
        $ConfigFile = Join-Path $ProjectRoot "config\yunxi.env.prod"
    }

    $templateFile = Join-Path $ProjectRoot "config\yunxi.env.prod.template"

    if (Test-Path $ConfigFile) {
        Write-Success "配置文件已存在: $ConfigFile"
        Write-Info "如需重新生成，请先删除现有配置文件"
        Add-DeployStep -Name "配置文件" -Status "EXISTS" -Detail $ConfigFile
        return $true
    }

    if (-not (Test-Path $templateFile)) {
        Write-Failure "配置模板文件不存在: $templateFile"
        Add-DeployStep -Name "配置文件" -Status "FAIL" -Detail "模板不存在"
        return $false
    }

    if (Invoke-CheckDryRun "将从模板生成配置文件: $ConfigFile") {
        Add-DeployStep -Name "配置文件" -Status "DRY-RUN"
        return $true
    }

    try {
        Copy-Item $templateFile $ConfigFile -Force
        Write-Success "配置文件已生成: $ConfigFile"
        Write-Warning "请务必修改所有 CHANGEME_ 开头的配置项！"
        Write-Warning "特别是：密钥、密码、数据库连接等敏感配置"
        Add-DeployStep -Name "配置文件" -Status "CREATED" -Detail $ConfigFile
        return $true
    }
    catch {
        Write-Failure "配置文件生成失败: $($_.Exception.Message)"
        Add-DeployStep -Name "配置文件" -Status "FAIL" -Detail $_.Exception.Message
        return $false
    }
}

# ============================================================
# 步骤 3: 依赖安装
# ============================================================

function Install-Dependencies {
    Write-StepHeader "步骤 3/7: 依赖安装（生产模式）"

    if (Invoke-CheckDryRun "将安装所有模块的生产依赖") {
        Add-DeployStep -Name "依赖安装" -Status "DRY-RUN"
        return $true
    }

    $successCount = 0
    $failCount = 0

    # 3.1 升级 pip
    Write-Info "升级 pip..."
    try {
        python -m pip install --upgrade pip 2>&1 | Out-Null
        Write-Success "pip 已升级到最新版本"
    }
    catch {
        Write-Warning "pip 升级失败: $($_.Exception.Message)"
    }

    # 3.2 安装 shared 依赖
    $sharedReq = Join-Path $ProjectRoot "shared\requirements.txt"
    if (Test-Path $sharedReq) {
        Write-Info "安装 shared 公共依赖..."
        try {
            pip install -r $sharedReq 2>&1 | Out-Null
            Write-Success "shared 依赖安装完成"
            $successCount++
        }
        catch {
            Write-Failure "shared 依赖安装失败: $($_.Exception.Message)"
            $failCount++
        }
    }

    # 3.3 安装各模块依赖
    foreach ($mod in $Modules) {
        $modDir = Join-Path $ProjectRoot $mod.Dir
        $reqFile = Join-Path $modDir "requirements.txt"

        if (-not (Test-Path $reqFile)) {
            # 尝试子目录
            $reqFile = Join-Path $modDir "backend\requirements.txt"
        }

        if (Test-Path $reqFile) {
            Write-Info "安装 $($mod.Name) 依赖..."
            try {
                pip install -r $reqFile 2>&1 | Out-Null
                Write-Success "$($mod.Name) 依赖安装完成"
                $successCount++
            }
            catch {
                Write-Failure "$($mod.Name) 依赖安装失败: $($_.Exception.Message)"
                $failCount++
            }
        }
        else {
            Write-Warning "$($mod.Name) 无 requirements.txt，跳过"
        }
    }

    Add-DeployStep -Name "依赖安装" -Status $(if ($failCount -eq 0) { "PASS" } else { "WARN" }) `
        -Detail "成功: $successCount, 失败: $failCount"

    return ($failCount -eq 0)
}

# ============================================================
# 步骤 4: 数据库初始化和迁移
# ============================================================

function Invoke-DbMigration {
    Write-StepHeader "步骤 4/7: 数据库初始化和迁移"

    if (Invoke-CheckDryRun "将执行数据库初始化和迁移") {
        Add-DeployStep -Name "数据库迁移" -Status "DRY-RUN"
        return $true
    }

    $successCount = 0
    $failCount = 0

    # 确保数据目录存在
    $dataDir = Join-Path $ProjectRoot "data"
    if (-not (Test-Path $dataDir)) {
        New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
        Write-Info "创建数据目录: $dataDir"
    }

    # 遍历各模块，查找数据库初始化脚本
    foreach ($mod in $Modules) {
        $modDir = Join-Path $ProjectRoot $mod.Dir

        # 查找可能的初始化脚本
        $initScripts = @(
            "init_db.py",
            "initialize_db.py",
            "db_init.py",
            "migrate.py",
            "alembic\env.py"
        )

        $foundScript = $null
        foreach ($script in $initScripts) {
            $scriptPath = Join-Path $modDir $script
            if (Test-Path $scriptPath) {
                $foundScript = $scriptPath
                break
            }
        }

        if ($foundScript) {
            Write-Info "执行 $($mod.Name) 数据库初始化..."
            try {
                Push-Location $modDir
                python (Split-Path $foundScript -Leaf) 2>&1 | Out-Null
                Pop-Location
                Write-Success "$($mod.Name) 数据库初始化完成"
                $successCount++
            }
            catch {
                Pop-Location
                Write-Warning "$($mod.Name) 数据库初始化失败: $($_.Exception.Message)"
                Write-Info "某些模块可能在首次启动时自动创建数据库，这是正常的"
                $failCount++
            }
        }
    }

    Write-Info "数据库文件将在各模块首次启动时自动创建（如尚未创建）"

    Add-DeployStep -Name "数据库迁移" -Status "DONE" -Detail "已初始化: $successCount 个模块"
    return $true
}

# ============================================================
# 步骤 5: 静态资源构建
# ============================================================

function Build-Frontend {
    Write-StepHeader "步骤 5/7: 前端静态资源构建"

    if (Invoke-CheckDryRun "将构建前端静态资源") {
        Add-DeployStep -Name "前端构建" -Status "DRY-RUN"
        return $true
    }

    $frontendDirs = @(
        "frontend\spa",
        "M7-workflow-builder\frontend",
        "M8-control-tower\frontend"
    )

    $builtCount = 0
    $skippedCount = 0

    foreach ($feDir in $frontendDirs) {
        $fullPath = Join-Path $ProjectRoot $feDir
        $packageJson = Join-Path $fullPath "package.json"

        if (-not (Test-Path $packageJson)) {
            Write-Warning "跳过 $feDir (package.json 不存在)"
            $skippedCount++
            continue
        }

        Write-Info "构建前端: $feDir..."

        # 检查 node 和 npm
        try {
            $null = node --version 2>&1
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "Node.js 未安装，跳过前端构建"
                Add-DeployStep -Name "前端构建" -Status "SKIP" -Detail "Node.js 未安装"
                return $true
            }
        }
        catch {
            Write-Warning "Node.js 检查失败，跳过前端构建: $($_.Exception.Message)"
            Add-DeployStep -Name "前端构建" -Status "SKIP" -Detail "Node.js 不可用"
            return $true
        }

        try {
            Push-Location $fullPath

            # 安装依赖
            if (-not (Test-Path "node_modules")) {
                Write-Info "  安装 npm 依赖..."
                npm install --production 2>&1 | Out-Null
            }

            # 构建
            Write-Info "  执行构建..."
            npm run build 2>&1 | Out-Null

            if ($LASTEXITCODE -eq 0) {
                Write-Success "$feDir 构建完成"
                $builtCount++
            }
            else {
                Write-Warning "$feDir 构建失败 (退出码: $LASTEXITCODE)"
            }

            Pop-Location
        }
        catch {
            Pop-Location
            Write-Warning "$feDir 构建异常: $($_.Exception.Message)"
        }
    }

    Add-DeployStep -Name "前端构建" -Status "DONE" -Detail "成功: $builtCount, 跳过: $skippedCount"
    return $true
}

# ============================================================
# 步骤 6: 服务启动
# ============================================================

function Start-Services {
    Write-StepHeader "步骤 6/7: 服务启动"

    if (Invoke-CheckDryRun "将启动所有服务模块") {
        Add-DeployStep -Name "服务启动" -Status "DRY-RUN"
        return $true
    }

    # 加载配置
    $envFile = if ($ConfigFile) { $ConfigFile } else { Join-Path $ProjectRoot "config\yunxi.env.prod" }
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
    else {
        Write-Warning "配置文件不存在: $envFile"
        Write-Info "将使用默认配置启动"
    }

    $startedPids = @{}
    $startedCount = 0
    $failedCount = 0

    # 按顺序启动各批次
    for ($order = 1; $order -le 4; $order++) {
        $batch = $Modules | Where-Object { $_.Order -eq $order }

        foreach ($mod in $batch) {
            $modDir = Join-Path $ProjectRoot $mod.Dir

            if (-not (Test-Path $modDir)) {
                Write-Warning "跳过 $($mod.Name) (目录不存在: $modDir)"
                continue
            }

            Write-Info "启动 $($mod.Name) (端口: $($mod.Port))..."

            # 检查端口是否已被占用
            $occupied = Get-NetTCPConnection -LocalPort $mod.Port -State Listen -ErrorAction SilentlyContinue
            if ($occupied) {
                Write-Warning "端口 $($mod.Port) 已被占用，跳过 $($mod.Name)"
                continue
            }

            try {
                $proc = Start-Process -FilePath "python" `
                    -ArgumentList $mod.Command `
                    -WorkingDirectory $modDir `
                    -WindowStyle Minimized `
                    -PassThru `
                    -ErrorAction Stop

                if ($proc) {
                    $startedPids[$mod.Dir] = $proc.Id
                    Write-Success "$($mod.Name) 启动成功 (PID: $($proc.Id))"
                    $startedCount++
                }
                else {
                    Write-Failure "$($mod.Name) 启动失败 (未获取到 PID)"
                    $failedCount++
                }
            }
            catch {
                Write-Failure "$($mod.Name) 启动异常: $($_.Exception.Message)"
                $failedCount++
            }

            Start-Sleep -Milliseconds 500
        }

        # 批次间等待
        if ($order -lt 4) {
            Write-Info "等待批次 $order 服务就绪..."
            Start-Sleep -Seconds 3
        }
    }

    # 保存 PID 文件
    if ($startedPids.Count -gt 0) {
        $pidFile = Join-Path $ProjectRoot ".deploy-prod-pids.json"
        $startedPids | ConvertTo-Json | Set-Content $pidFile -Encoding UTF8
        Write-Info "PID 文件已保存: $pidFile"
    }

    Add-DeployStep -Name "服务启动" -Status $(if ($failedCount -eq 0) { "PASS" } else { "WARN" }) `
        -Detail "成功: $startedCount, 失败: $failedCount"

    return $true
}

# ============================================================
# 步骤 7: 健康检查
# ============================================================

function Invoke-HealthCheck {
    Write-StepHeader "步骤 7/7: 健康检查"

    if (Invoke-CheckDryRun "将执行服务健康检查") {
        Add-DeployStep -Name "健康检查" -Status "DRY-RUN"
        return $true
    }

    $healthTimeout = 120
    $deadline = (Get-Date).AddSeconds($healthTimeout)
    $healthyModules = @()
    $unhealthyModules = @()

    Write-Info "等待服务健康就绪 (超时: ${healthTimeout}s)..."

    while ((Get-Date) -lt $deadline) {
        $allHealthy = $true

        foreach ($mod in $Modules) {
            if ($healthyModules -contains $mod.Name) { continue }

            $healthUrl = "http://localhost:$($mod.Port)/health"

            try {
                $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3 -ErrorAction Stop
                $isHealthy = $response.status -eq "ok" -or $response.status -eq "healthy" -or $response.code -eq 0

                if ($isHealthy) {
                    $healthyModules += $mod.Name
                    Write-Success "$($mod.Name) 健康检查通过"
                }
                else {
                    $allHealthy = $false
                }
            }
            catch {
                $allHealthy = $false
            }
        }

        if ($allHealthy -or $healthyModules.Count -eq $Modules.Count) {
            break
        }

        Start-Sleep -Seconds 5
    }

    # 标记未通过健康检查的模块
    foreach ($mod in $Modules) {
        if ($healthyModules -notcontains $mod.Name) {
            $unhealthyModules += $mod.Name
        }
    }

    if ($unhealthyModules.Count -gt 0) {
        Write-Warning "以下模块健康检查未通过: $($unhealthyModules -join ', ')"
        Write-Info "可能原因：启动较慢、配置错误、依赖未就绪等"
        Write-Info "可使用 .\scripts\health-check.ps1 进一步检查"
    }
    else {
        Write-Success "所有模块健康检查通过"
    }

    Add-DeployStep -Name "健康检查" -Status $(if ($unhealthyModules.Count -eq 0) { "PASS" } else { "WARN" }) `
        -Detail "健康: $($healthyModules.Count)/$($Modules.Count)"

    return ($unhealthyModules.Count -eq 0)
}

# ============================================================
# 部署报告
# ============================================================

function Show-DeployReport {
    Write-StepHeader "部署结果报告"

    $endTime = Get-Date
    $duration = ($endTime - $Script:DeployStartTime).TotalSeconds

    Write-Host "部署时间: $($Script:DeployStartTime.ToString('yyyy-MM-dd HH:mm:ss')) -> $($endTime.ToString('yyyy-MM-dd HH:mm:ss'))"
    Write-Host "总耗时: $([math]::Round($duration, 2)) 秒"
    Write-Host ""

    Write-Host "步骤详情:" -ForegroundColor Cyan
    Write-Host "--------"
    foreach ($step in $Script:DeploySteps) {
        $statusColor = switch ($step.Status) {
            "PASS" { "Green" }
            "CREATED" { "Green" }
            "DONE" { "Green" }
            "EXISTS" { "Yellow" }
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
    if ($Script:DeployErrors.Count -gt 0) {
        $overallStatus = "FAILED"
        $overallColor = "Red"
    }
    elseif ($Script:DeployWarnings.Count -gt 0) {
        $overallStatus = "PARTIAL"
        $overallColor = "Yellow"
    }

    Write-Host "总体状态: $overallStatus" -ForegroundColor $overallColor
    Write-Host "错误数: $($Script:DeployErrors.Count)"
    Write-Host "警告数: $($Script:DeployWarnings.Count)"
    Write-Host ""

    if ($Script:DeployErrors.Count -gt 0) {
        Write-Host "错误列表:" -ForegroundColor Red
        foreach ($err in $Script:DeployErrors) {
            Write-Host "  - $err" -ForegroundColor Red
        }
        Write-Host ""
    }

    if ($DryRun) {
        Write-Host "[DRY-RUN] 这是试运行，未执行实际操作" -ForegroundColor Magenta
    }
    else {
        Write-Host "停止服务: .\stop-all.ps1" -ForegroundColor Gray
        Write-Host "健康检查: .\scripts\health-check.ps1" -ForegroundColor Gray
        Write-Host "查看日志: .\scripts\logs.ps1" -ForegroundColor Gray
    }
    Write-Host ""
}

# ============================================================
# 主流程
# ============================================================

function Main {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor White
    Write-Host "  云汐系统 - 生产环境部署" -ForegroundColor White
    Write-Host "========================================" -ForegroundColor White
    Write-Host ""
    Write-Host "项目根目录: $ProjectRoot"
    if ($DryRun) { Write-Host "模式: DRY-RUN (试运行)" -ForegroundColor Magenta }
    Write-Host ""

    $overallSuccess = $true

    # 步骤 1: 环境检查
    if (-not $SkipEnvCheck) {
        if (-not (Test-Environment)) {
            if (-not $Force) {
                Write-Failure "环境检查未通过，部署终止"
                $overallSuccess = $false
            }
        }
    }
    else {
        Write-Info "跳过环境检查"
        Add-DeployStep -Name "环境检查" -Status "SKIP"
    }

    # 步骤 2: 配置文件
    if (-not (New-ConfigFile)) {
        $overallSuccess = $false
    }

    # 步骤 3: 依赖安装
    if (-not $SkipDependencyInstall) {
        if (-not (Install-Dependencies)) {
            Write-Warning "部分依赖安装失败，尝试继续部署..."
        }
    }
    else {
        Write-Info "跳过依赖安装"
        Add-DeployStep -Name "依赖安装" -Status "SKIP"
    }

    # 步骤 4: 数据库迁移
    if (-not $SkipDbMigration) {
        Invoke-DbMigration | Out-Null
    }
    else {
        Write-Info "跳过数据库迁移"
        Add-DeployStep -Name "数据库迁移" -Status "SKIP"
    }

    # 步骤 5: 前端构建
    if (-not $SkipFrontendBuild) {
        Build-Frontend | Out-Null
    }
    else {
        Write-Info "跳过前端构建"
        Add-DeployStep -Name "前端构建" -Status "SKIP"
    }

    # 步骤 6: 服务启动
    Start-Services | Out-Null

    # 步骤 7: 健康检查
    Invoke-HealthCheck | Out-Null

    # 部署报告
    Show-DeployReport

    if ($overallSuccess -and $Script:DeployErrors.Count -eq 0) {
        exit 0
    }
    else {
        exit 1
    }
}

Main
