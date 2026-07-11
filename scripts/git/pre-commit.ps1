<#
.SYNOPSIS
云汐系统 v1.1 - Git Pre-Commit 钩子脚本 (GIT-01)

.DESCRIPTION
PowerShell 版本的 pre-commit 钩子，调用 Python 核心检查逻辑
功能包括：
  1. Python 语法检查
  2. Import 排序检查
  3. 大文件扫描
  4. 敏感信息扫描
  5. 关联单元测试

.NOTES
此脚本由 install_hooks.ps1 安装到 .git/hooks/ 目录
返回值: 0 = 通过, 非 0 = 阻止提交
#>

$ErrorActionPreference = "Stop"

# 获取脚本所在目录（可能在 .git/hooks/ 或 scripts/git/ 中）
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 查找 Python 检查脚本
$PyScript = Join-Path $ScriptDir "run_precommit.py"

# 如果当前在 hooks 目录，向上查找项目 scripts/git 目录
if (-not (Test-Path $PyScript)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)  # .git 的父目录
    $PyScript = Join-Path $ProjectRoot "scripts\git\run_precommit.py"
}

if (-not (Test-Path $PyScript)) {
    Write-Host "错误: 找不到 run_precommit.py" -ForegroundColor Red
    Write-Host "  查找路径: $PyScript" -ForegroundColor Yellow
    exit 1
}

# 查找 Python 解释器
$PythonExe = $null
$possiblePythons = @("python", "python3", "py")
foreach ($p in $possiblePythons) {
    $cmd = Get-Command $p -ErrorAction SilentlyContinue
    if ($cmd) {
        $PythonExe = $cmd.Source
        break
    }
}

if (-not $PythonExe) {
    Write-Host "警告: 未找到 Python，跳过 pre-commit 检查" -ForegroundColor Yellow
    Write-Host "  提示: 安装 Python 3.8+ 以启用代码检查" -ForegroundColor Yellow
    exit 0
}

# 运行 Python 检查脚本
try {
    & $PythonExe $PyScript
    $exitCode = $LASTEXITCODE
}
catch {
    Write-Host "Pre-commit 检查执行异常: $_" -ForegroundColor Red
    exit 1
}

if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  提交被阻止！请修复上述问题后再提交。" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "如需临时跳过（不推荐），使用: git commit --no-verify" -ForegroundColor Yellow
    exit $exitCode
}

exit 0
