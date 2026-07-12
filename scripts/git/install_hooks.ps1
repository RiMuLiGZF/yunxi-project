<#
.SYNOPSIS
云汐系统 v1.1 - Git 钩子安装脚本 (GIT-01)

.DESCRIPTION
安装 pre-commit 和 commit-msg 钩子到当前 Git 仓库
将 PowerShell 脚本包装为可被 Git 调用的钩子

.NOTES
用法: .\install_hooks.ps1
       - 安装所有钩子
     .\install_hooks.ps1 -Uninstall
       - 卸载所有钩子
     .\install_hooks.ps1 -Force
       - 强制覆盖已存在的钩子
#>

param(
    [switch]$Uninstall,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# 获取脚本所在目录（scripts/git/）
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)  # 项目根目录
$GitDir = Join-Path $ProjectRoot ".git"
$HooksDir = Join-Path $GitDir "hooks"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  云汐系统 Git 钩子安装器 (GIT-01)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "项目根目录: $ProjectRoot"
Write-Host "Git 目录:   $GitDir"
Write-Host ""

# 检查是否为 Git 仓库
if (-not (Test-Path $GitDir)) {
    Write-Host "错误: 当前目录不是 Git 仓库（未找到 .git 目录）" -ForegroundColor Red
    Write-Host "  请先运行: git init" -ForegroundColor Yellow
    exit 1
}

# 创建 hooks 目录（如果不存在）
if (-not (Test-Path $HooksDir)) {
    New-Item -ItemType Directory -Path $HooksDir -Force | Out-Null
    Write-Host "已创建 hooks 目录" -ForegroundColor Green
}

# 定义需要安装的钩子
$hooks = @(
    @{ Name = "pre-commit"; Source = "pre-commit.ps1"; Desc = "提交前代码检查" },
    @{ Name = "commit-msg"; Source = "commit-msg.ps1"; Desc = "提交信息格式检查" }
)

if ($Uninstall) {
    Write-Host "正在卸载 Git 钩子..." -ForegroundColor Yellow
    Write-Host ""

    $removed = 0
    foreach ($hook in $hooks) {
        $hookPath = Join-Path $HooksDir $hook.Name

        if (Test-Path $hookPath) {
            Remove-Item $hookPath -Force
            Write-Host "  ✓ 已卸载 $($hook.Name) ($($hook.Desc))" -ForegroundColor Green
            $removed++
        }
        else {
            Write-Host "  - $($hook.Name) 不存在，跳过" -ForegroundColor Gray
        }

        # 也删除 .sample 文件（如果是我们创建的）
        $samplePath = "$hookPath.sample"
        if (Test-Path $samplePath) {
            Remove-Item $samplePath -Force
        }
    }

    Write-Host ""
    Write-Host "卸载完成，共移除 $removed 个钩子" -ForegroundColor Green
    exit 0
}

# 安装钩子
Write-Host "正在安装 Git 钩子..." -ForegroundColor Yellow
Write-Host ""

$installed = 0
$skipped = 0

foreach ($hook in $hooks) {
    $hookPath = Join-Path $HooksDir $hook.Name
    $sourcePath = Join-Path $ScriptDir $hook.Source

    # 检查源文件是否存在
    if (-not (Test-Path $sourcePath)) {
        Write-Host "  ✗ $($hook.Name): 源文件不存在 ($sourcePath)" -ForegroundColor Red
        continue
    }

    # 检查是否已存在
    if ((Test-Path $hookPath) -and (-not $Force)) {
        Write-Host "  - $($hook.Name): 已存在，跳过（使用 -Force 覆盖）" -ForegroundColor Yellow
        $skipped++
        continue
    }

    # 备份原有钩子
    if ((Test-Path $hookPath) -and $Force) {
        $backupPath = "$hookPath.bak.$(Get-Date -Format 'yyyyMMddHHmmss')"
        Copy-Item $hookPath $backupPath -Force
        Write-Host "    已备份原钩子到: $backupPath" -ForegroundColor Gray
    }

    # 创建钩子脚本（bash 兼容格式，调用 PowerShell）
    # Git 在 Windows 上通过 Git Bash 运行钩子，所以需要一个 bash 包装器
    $hookContent = @"
#!/bin/sh
# 云汐系统 Git 钩子: $($hook.Name)
# 自动生成 - 请勿手动修改
# 调用 PowerShell 版本的钩子脚本

SCRIPT_DIR="`$(cd "\`$(dirname "\`$0")" && pwd)"
PROJECT_ROOT="`$(dirname "\`$(dirname "\`$SCRIPT_DIR")")"

# Windows 下调用 PowerShell
if command -v powershell.exe >/dev/null 2>&1; then
    # 将路径转换为 Windows 格式
    WIN_SCRIPT="`$(cygpath -w "\`$PROJECT_ROOT/scripts/git/$($hook.Source)")"
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "`$WIN_SCRIPT" "\`$@"
    exit `$?
elif command -v pwsh >/dev/null 2>&1; then
    pwsh -NoProfile -ExecutionPolicy Bypass -File "`$PROJECT_ROOT/scripts/git/$($hook.Source)" "\`$@"
    exit `$?
else
    echo "警告: 未找到 PowerShell，跳过 $($hook.Name) 检查"
    exit 0
fi
"@

    # 写入钩子文件
    Set-Content -Path $hookPath -Value $hookContent -Encoding UTF8 -NoNewline
    $installed++

    Write-Host "  ✓ 已安装 $($hook.Name) ($($hook.Desc))" -ForegroundColor Green
}

Write-Host ""
Write-Host "安装完成: $installed 个已安装, $skipped 个跳过" -ForegroundColor Green
Write-Host ""
Write-Host "提示:" -ForegroundColor Cyan
Write-Host "  - 钩子脚本位于: scripts/git/" -ForegroundColor White
Write-Host "  - 核心检查逻辑: scripts/git/run_precommit.py" -ForegroundColor White
Write-Host "  - 卸载钩子:     .\scripts\git\install_hooks.ps1 -Uninstall" -ForegroundColor White
Write-Host "  - 跳过检查:     git commit --no-verify" -ForegroundColor White
Write-Host ""

exit 0
