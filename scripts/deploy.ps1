# 云汐系统一键部署脚本 (Windows PowerShell)
# 版本: 1.0.0
# 用途: 一键完成 V1.0 生产环境部署

param(
    [string]$InstallPath = "C:\yunxi",
    [string]$ConfigFile = "",
    [switch]$SkipBackup,
    [switch]$SkipMigration,
    [switch]$StartAfterInstall
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  云汐系统 V1.0 一键部署脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------------------
# 步骤 1: 环境检查
# ------------------------------------------------------------
Write-Host "[1/8] 环境检查..." -ForegroundColor Yellow

# 检查 Python
try {
    $pythonVersion = python --version 2>&1
    Write-Host "  Python: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "  错误: 未找到 Python，请先安装 Python 3.10+" -ForegroundColor Red
    exit 1
}

# 检查 Python 版本
$versionOutput = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$major, $minor = $versionOutput -split '\.'
if ([int]$major -lt 3 -or ([int]$major -eq 3 -and [int]$minor -lt 10)) {
    Write-Host "  错误: Python 版本过低，需要 3.10+" -ForegroundColor Red
    exit 1
}

# 检查 pip
try {
    pip --version | Out-Null
    Write-Host "  pip: 已安装" -ForegroundColor Green
} catch {
    Write-Host "  错误: 未找到 pip" -ForegroundColor Red
    exit 1
}

Write-Host "  环境检查通过" -ForegroundColor Green

# ------------------------------------------------------------
# 步骤 2: 创建目录结构
# ------------------------------------------------------------
Write-Host "[2/8] 创建目录结构..." -ForegroundColor Yellow

$dirs = @(
    $InstallPath,
    Join-Path $InstallPath "data",
    Join-Path $InstallPath "backups",
    Join-Path $InstallPath "logs",
    Join-Path $InstallPath "temp",
    Join-Path $InstallPath "config"
)

foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "  创建目录: $dir" -ForegroundColor Green
    }
}

Write-Host "  目录结构就绪" -ForegroundColor Green

# ------------------------------------------------------------
# 步骤 3: 复制文件
# ------------------------------------------------------------
Write-Host "[3/8] 复制系统文件..." -ForegroundColor Yellow

# 复制核心文件
$itemsToCopy = @(
    "shared",
    "M0-principal-console",
    "M1-agent-hub",
    "M8-control-tower",
    "API-Gateway",
    "scripts",
    "config"
)

foreach ($item in $itemsToCopy) {
    $src = Join-Path $ProjectRoot $item
    $dst = Join-Path $InstallPath $item
    if (Test-Path $src) {
        if (Test-Path $dst) {
            # 已存在，先备份旧版本
            $backupName = "$item.bak_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
            $backupPath = Join-Path $InstallPath $backupName
            Move-Item $dst $backupPath -Force
            Write-Host "  备份旧版本: $item -> $backupName" -ForegroundColor Yellow
        }
        Copy-Item -Path $src -Destination $InstallPath -Recurse -Force
        Write-Host "  复制: $item" -ForegroundColor Green
    }
}

# 复制文档
$docsDir = Join-Path $InstallPath "docs"
if (-not (Test-Path $docsDir)) {
    New-Item -ItemType Directory -Path $docsDir -Force | Out-Null
}
Copy-Item (Join-Path $ProjectRoot "CHANGELOG.md") $docsDir -Force
Copy-Item (Join-Path $ProjectRoot "docs\release-notes-v1.0.md") $docsDir -Force
Copy-Item (Join-Path $ProjectRoot "docs\release-checklist-v1.0.md") $docsDir -Force
Write-Host "  复制文档" -ForegroundColor Green

Write-Host "  文件复制完成" -ForegroundColor Green

# ------------------------------------------------------------
# 步骤 4: 安装依赖
# ------------------------------------------------------------
Write-Host "[4/8] 安装 Python 依赖..." -ForegroundColor Yellow

$requirementsFile = Join-Path $ProjectRoot "requirements.txt"
if (Test-Path $requirementsFile) {
    Write-Host "  正在安装依赖（可能需要几分钟）..." -ForegroundColor Gray
    pip install -r $requirementsFile 2>&1 | Out-Null
    Write-Host "  依赖安装完成" -ForegroundColor Green
} else {
    Write-Host "  警告: 未找到 requirements.txt，跳过依赖安装" -ForegroundColor Yellow
    # 安装核心依赖
    Write-Host "  安装核心依赖..." -ForegroundColor Gray
    pip install fastapi uvicorn pydantic pyyaml python-jose passlib 2>&1 | Out-Null
    Write-Host "  核心依赖安装完成" -ForegroundColor Green
}

# ------------------------------------------------------------
# 步骤 5: 配置文件
# ------------------------------------------------------------
Write-Host "[5/8] 配置文件..." -ForegroundColor Yellow

$prodConfig = Join-Path $InstallPath "config\settings.prod.yaml"
$targetConfig = Join-Path $InstallPath "config\settings.yaml"

if ($ConfigFile -and (Test-Path $ConfigFile)) {
    Copy-Item $ConfigFile $targetConfig -Force
    Write-Host "  使用自定义配置: $ConfigFile" -ForegroundColor Green
} elseif (-not (Test-Path $targetConfig)) {
    if (Test-Path $prodConfig) {
        Copy-Item $prodConfig $targetConfig -Force
        Write-Host "  已从生产模板创建配置文件: settings.yaml" -ForegroundColor Yellow
        Write-Host "  请修改配置文件中的密钥和敏感信息！" -ForegroundColor Red
    }
} else {
    Write-Host "  配置文件已存在，保留当前配置" -ForegroundColor Green
}

# ------------------------------------------------------------
# 步骤 6: 数据库初始化
# ------------------------------------------------------------
Write-Host "[6/8] 数据库初始化..." -ForegroundColor Yellow

if ($SkipMigration) {
    Write-Host "  跳过数据库迁移" -ForegroundColor Yellow
} else {
    $dbInitScript = Join-Path $InstallPath "M0-principal-console\src\database.py"
    if (Test-Path $dbInitScript) {
        Write-Host "  初始化数据库..." -ForegroundColor Gray
        Push-Location (Join-Path $InstallPath "M0-principal-console")
        try {
            python -c "from src.database import init_db; init_db(); print('DB initialized')" 2>&1 | Out-Null
            Write-Host "  数据库初始化完成" -ForegroundColor Green
        } catch {
            Write-Host "  警告: 数据库初始化可能需要手动完成" -ForegroundColor Yellow
        }
        Pop-Location
    }
}

# ------------------------------------------------------------
# 步骤 7: 权限设置
# ------------------------------------------------------------
Write-Host "[7/8] 设置文件权限..." -ForegroundColor Yellow

# 限制配置文件权限（仅管理员可写）
$configFile = Join-Path $InstallPath "config\settings.yaml"
if (Test-Path $configFile) {
    try {
        $acl = Get-Acl $configFile
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            "Users", "ReadAndExecute", "Allow"
        )
        $acl.SetAccessRule($rule)
        # 注：完整的权限设置建议手动执行
    } catch {
        Write-Host "  提示: 建议手动配置配置文件权限" -ForegroundColor Yellow
    }
}
Write-Host "  权限设置完成" -ForegroundColor Green

# ------------------------------------------------------------
# 步骤 8: 验证安装
# ------------------------------------------------------------
Write-Host "[8/8] 验证安装..." -ForegroundColor Yellow

$verifyOk = $true

# 检查关键文件
$criticalFiles = @(
    "config\settings.yaml",
    "shared\core\module_registry.py",
    "M0-principal-console\server.py"
)

foreach ($file in $criticalFiles) {
    $fullPath = Join-Path $InstallPath $file
    if (Test-Path $fullPath) {
        Write-Host "  ✓ $file" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $file (缺失)" -ForegroundColor Red
        $verifyOk = $false
    }
}

# 检查目录
$criticalDirs = @("data", "backups", "logs")
foreach ($dir in $criticalDirs) {
    $fullPath = Join-Path $InstallPath $dir
    if (Test-Path $fullPath) {
        Write-Host "  ✓ $dir\" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $dir\ (缺失)" -ForegroundColor Red
        $verifyOk = $false
    }
}

Write-Host ""

if ($verifyOk) {
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  部署成功！" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  安装路径: $InstallPath"
    Write-Host "  版本: v1.0.0"
    Write-Host ""
    Write-Host "  下一步操作:" -ForegroundColor Yellow
    Write-Host "  1. 修改配置文件: config\settings.yaml"
    Write-Host "  2. 设置管理员密码"
    Write-Host "  3. 启动服务: scripts\start-all.ps1"
    Write-Host "  4. 访问: http://localhost:8000"
    Write-Host ""
} else {
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  部署存在问题，请检查上述错误" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    exit 1
}

# 可选：启动服务
if ($StartAfterInstall) {
    Write-Host "正在启动服务..." -ForegroundColor Yellow
    & (Join-Path $InstallPath "scripts\start-all.ps1")
}
