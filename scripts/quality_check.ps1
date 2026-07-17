<#
.SYNOPSIS
云汐系统 - 代码质量一键检查脚本

.DESCRIPTION
一键运行所有代码质量检查工具，输出综合质量报告。
检查项包括：Ruff Lint、Ruff Format、Mypy、Bandit、Radon、测试覆盖率

.NOTES
使用方式:
    .\scripts\quality_check.ps1              # 运行所有检查
    .\scripts\quality_check.ps1 -Quick       # 快速检查（仅 lint + format）
    .\scripts\quality\_check.ps1 -CoreOnly   # 仅核心模块
    .\scripts\quality_check.ps1 -Fix         # 自动修复可修复的问题

作者: 云汐团队
版本: 1.0.0
#>

param(
    [switch]$Quick,        # 快速模式：仅 lint + format
    [switch]$CoreOnly,     # 仅检查核心模块
    [switch]$Fix,          # 自动修复模式
    [switch]$NoTests,      # 不运行测试
    [string]$ReportDir = "tests\reports\quality"  # 报告输出目录
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

# 创建报告目录
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

$results = @{}
$totalChecks = 0
$passedChecks = 0

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  云汐系统 - 代码质量检查" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "项目根目录: $ProjectRoot"
Write-Host "报告目录: $ReportDir"
Write-Host "模式: $(if ($Quick) { "快速" } elseif ($CoreOnly) { "核心模块" } else { "全量" })"
Write-Host ""

# 确定检查范围
if ($CoreOnly) {
    $CheckPaths = @("shared\core", "shared\data")
} else {
    $CheckPaths = @("shared", "M8-control-tower\backend", "M9-dev-workshop\backend", "M11-mcp-bus\src", "M12-security-shield", "API-Gateway")
}

function Invoke-Check {
    param(
        [string]$Name,
        [string]$Command,
        [string]$OutputFile = ""
    )

    $global:totalChecks++
    Write-Host "[$global:totalChecks] $Name ... " -NoNewline

    try {
        if ($OutputFile) {
            $output = Invoke-Expression $Command 2>&1
            $output | Out-File -FilePath "$ReportDir\$OutputFile" -Encoding utf8
            $exitCode = $LASTEXITCODE
        } else {
            $output = Invoke-Expression $Command 2>&1
            $exitCode = $LASTEXITCODE
        }

        if ($exitCode -eq 0) {
            Write-Host "PASS" -ForegroundColor Green
            $global:passedChecks++
            $global:results[$Name] = "PASS"
        } else {
            Write-Host "WARN" -ForegroundColor Yellow
            $global:results[$Name] = "WARN ($exitCode issues)"
        }
    } catch {
        Write-Host "FAIL" -ForegroundColor Red
        $global:results[$Name] = "FAIL ($($_.Exception.Message))"
    }
}

# ============================================================
# 1. Ruff 代码风格检查
# ============================================================
$ruffFixArg = if ($Fix) { "--fix" } else { "" }
$checkCmd = "ruff check $($CheckPaths -join ' ') $ruffFixArg --statistics"
Invoke-Check -Name "Ruff Lint (代码风格)" -Command $checkCmd -OutputFile "ruff_lint.txt"

# ============================================================
# 2. Ruff 格式化检查
# ============================================================
if ($Fix) {
    $formatCmd = "ruff format $($CheckPaths -join ' ')"
    Invoke-Check -Name "Ruff Format (代码格式化)" -Command $formatCmd
} else {
    $formatCheckCmd = "ruff format --check $($CheckPaths -join ' ')"
    Invoke-Check -Name "Ruff Format (格式化检查)" -Command $formatCheckCmd -OutputFile "ruff_format.txt"
}

# ============================================================
# 快速模式到此结束
# ============================================================
if ($Quick) {
    goto Summary
}

# ============================================================
# 3. Mypy 类型检查
# ============================================================
$mypyPaths = if ($CoreOnly) { "shared\core shared\data" } else { "shared\core shared\data shared\business" }
$mypyCmd = "mypy $mypyPaths --config-file=pyproject.toml --no-error-summary"
Invoke-Check -Name "Mypy (类型检查)" -Command $mypyCmd -OutputFile "mypy.txt"

# ============================================================
# 4. Bandit 安全扫描
# ============================================================
$banditPaths = if ($CoreOnly) { "shared\core shared\data" } else { "shared M8-control-tower M9-dev-workshop M11-mcp-bus M12-security-shield" }
$banditCmd = "bandit -r $banditPaths -c .bandit -ll -f json -o `"$ReportDir\bandit.json`" 2>&1"
Invoke-Check -Name "Bandit (安全扫描)" -Command $banditCmd

# ============================================================
# 5. Radon 圈复杂度
# ============================================================
$radonPaths = if ($CoreOnly) { "shared\core shared\data" } else { "shared\core shared\data" }
$radonCmd = "radon cc $radonPaths -a -nc --total-average -x tests,__pycache__"
Invoke-Check -Name "Radon CC (圈复杂度)" -Command $radonCmd -OutputFile "radon_cc.txt"

# ============================================================
# 6. Radon 可维护性指数
# ============================================================
$radonMiCmd = "radon mi $radonPaths -s -x tests,__pycache__"
Invoke-Check -Name "Radon MI (可维护性)" -Command $radonMiCmd -OutputFile "radon_mi.txt"

# ============================================================
# 7. 单元测试与覆盖率
# ============================================================
if (-not $NoTests) {
    $testCmd = "pytest tests/test_shared/ shared/tests/ -m `"unit and not slow`" --tb=short " + `
               "--cov=shared/core --cov=shared/data --cov=shared/business " + `
               "--cov-report=term-missing --cov-report=html:`"$ReportDir\coverage_html`" " + `
               "--cov-config=.coveragerc --timeout=30 -q"
    Invoke-Check -Name "单元测试 + 覆盖率" -Command $testCmd
}

# ============================================================
# 汇总报告
# ============================================================
Summary:

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  质量检查汇总" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

foreach ($name in $results.Keys) {
    $status = $results[$name]
    if ($status -like "PASS*") {
        Write-Host "  [PASS]  " -ForegroundColor Green -NoNewline
    } elseif ($status -like "WARN*") {
        Write-Host "  [WARN]  " -ForegroundColor Yellow -NoNewline
    } else {
        Write-Host "  [FAIL]  " -ForegroundColor Red -NoNewline
    }
    Write-Host $name
}

Write-Host ""
$passRate = if ($totalChecks -gt 0) { [math]::Round(($passedChecks / $totalChecks) * 100, 1) } else { 0 }
Write-Host "通过率: $passedChecks / $totalChecks ($passRate%)"

if ($passRate -ge 90) {
    Write-Host "质量评级: A (优秀)" -ForegroundColor Green
} elseif ($passRate -ge 75) {
    Write-Host "质量评级: B (良好)" -ForegroundColor Cyan
} elseif ($passRate -ge 60) {
    Write-Host "质量评级: C (合格)" -ForegroundColor Yellow
} else {
    Write-Host "质量评级: D (需改进)" -ForegroundColor Red
}

Write-Host ""
Write-Host "详细报告目录: $ReportDir"
Write-Host ""

# 返回退出码（0 = 全部通过，1 = 有警告，2 = 有失败）
if ($passedChecks -eq $totalChecks) {
    exit 0
} elseif ($results.Values -like "FAIL*") {
    exit 2
} else {
    exit 1
}
