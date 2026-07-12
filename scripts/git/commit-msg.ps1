<#
.SYNOPSIS
云汐系统 v1.1 - Git Commit-Msg 钩子脚本 (GIT-01)

.DESCRIPTION
检查提交信息是否符合 Conventional Commits 规范
格式: <type>(<scope>): <subject>
示例: feat(m8): add git status dashboard
      fix(auth): resolve login timeout issue

.NOTES
此脚本由 install_hooks.ps1 安装到 .git/hooks/ 目录
参数: $args[0] = 提交信息文件路径
返回值: 0 = 通过, 非 0 = 阻止提交
#>

$ErrorActionPreference = "Stop"

# 提交信息文件路径（git 传入的第一个参数）
$MsgFile = $args[0]

if (-not $MsgFile) {
    Write-Host "错误: 未提供提交信息文件路径" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $MsgFile)) {
    Write-Host "错误: 提交信息文件不存在: $MsgFile" -ForegroundColor Red
    exit 1
}

# 获取脚本所在目录
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 查找 Python 检查脚本
$PyScript = Join-Path $ScriptDir "run_precommit.py"

# 如果当前在 hooks 目录，向上查找项目 scripts/git 目录
if (-not (Test-Path $PyScript)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
    $PyScript = Join-Path $ProjectRoot "scripts\git\run_precommit.py"
}

if (-not (Test-Path $PyScript)) {
    Write-Host "警告: 找不到 run_precommit.py，跳过 commit-msg 检查" -ForegroundColor Yellow
    exit 0
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
    Write-Host "警告: 未找到 Python，跳过 commit-msg 检查" -ForegroundColor Yellow
    exit 0
}

# 运行 Python 检查脚本（commit-msg 模式）
try {
    & $PythonExe $PyScript --commit-msg $MsgFile
    $exitCode = $LASTEXITCODE
}
catch {
    Write-Host "Commit-msg 检查执行异常: $_" -ForegroundColor Red
    exit 1
}

if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  提交被阻止！提交信息格式不符合规范。" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "Conventional Commits 格式:" -ForegroundColor Cyan
    Write-Host "  <type>(<scope>): <subject>" -ForegroundColor White
    Write-Host ""
    Write-Host "常用 type:" -ForegroundColor Cyan
    Write-Host "  feat    - 新功能" -ForegroundColor White
    Write-Host "  fix     - 修复 bug" -ForegroundColor White
    Write-Host "  docs    - 文档变更" -ForegroundColor White
    Write-Host "  style   - 代码格式（不影响功能）" -ForegroundColor White
    Write-Host "  refactor- 重构" -ForegroundColor White
    Write-Host "  perf    - 性能优化" -ForegroundColor White
    Write-Host "  test    - 测试相关" -ForegroundColor White
    Write-Host "  chore   - 构建/工具/依赖等" -ForegroundColor White
    Write-Host ""
    Write-Host "示例:" -ForegroundColor Cyan
    Write-Host "  feat(m8): add git status dashboard" -ForegroundColor White
    Write-Host "  fix(auth): resolve login timeout" -ForegroundColor White
    Write-Host ""
    Write-Host "如需临时跳过（不推荐），使用: git commit --no-verify" -ForegroundColor Yellow
    exit $exitCode
}

exit 0
