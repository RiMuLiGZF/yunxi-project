<#
.SYNOPSIS
云汐系统健康检查脚本
.DESCRIPTION
检查所有模块的健康状态
#>

$Modules = @(
    @{ Name = "M8 管理台"; Url = "http://localhost:8000/api/health" },
    @{ Name = "M1 Agent调度"; Url = "http://localhost:8001/health" },
    @{ Name = "M2 技能集群"; Url = "http://localhost:8002/api/health" },
    @{ Name = "M3 端云协同"; Url = "http://localhost:8003/api/health" },
    @{ Name = "M4 场景引擎"; Url = "http://localhost:8004/health" },
    @{ Name = "M5 潮汐记忆"; Url = "http://localhost:8005/health" },
    @{ Name = "M6 硬件外设"; Url = "http://localhost:8006/api/v1/health" },
    @{ Name = "M7 积木平台"; Url = "http://localhost:3001/api/v1/health" }
)

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  🌊  云汐系统健康检查" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

$okCount = 0
$failCount = 0

foreach ($mod in $Modules) {
    try {
        $resp = Invoke-RestMethod -Uri $mod.Url -TimeoutSec 3 -ErrorAction Stop
        $status = if ($resp.code -eq 0 -or $resp.status -eq "ok" -or $resp.status -eq "healthy" -or $resp.code -eq 200) { "正常" } else { "异常" }
        Write-Host "  [正常] $($mod.Name) " -ForegroundColor Green
        $okCount++
    } catch {
        $errMsg = $_.Exception.Message
        if ($errMsg -match "actively refused") {
            Write-Host "  [离线] $($mod.Name) - 连接被拒绝" -ForegroundColor Red
        } else {
            Write-Host "  [异常] $($mod.Name) - $errMsg" -ForegroundColor Red
        }
        $failCount++
    }
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  检查完成: $okCount 正常 / $failCount 异常" -ForegroundColor $(if ($failCount -eq 0) { "Green" } else { "Yellow" })
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

if ($failCount -eq 0) {
    Write-Host "  ✅ 全部模块运行正常" -ForegroundColor Green
} else {
    Write-Host "  ⚠️  部分模块异常，请检查" -ForegroundColor Yellow
}
Write-Host ""
