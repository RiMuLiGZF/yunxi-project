<#
.SYNOPSIS
停止所有云汐模块
.DESCRIPTION
通过端口查找并停止所有云汐相关进程
#>

$Ports = @(8000, 8001, 8002, 8003, 8004, 8005, 8006, 3001)

$Names = @{
    8000 = "M8 管理台"
    8001 = "M1 Agent调度"
    8002 = "M2 技能集群"
    8003 = "M3 端云协同"
    8004 = "M4 场景引擎"
    8005 = "M5 潮汐记忆"
    8006 = "M6 硬件外设"
    3001 = "M7 积木平台"
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  停止云汐所有模块" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

$stopped = 0
foreach ($port in $Ports) {
    $name = $Names[$port]
    try {
        $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
        if ($conns) {
            $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
            foreach ($pid in $pids) {
                try {
                    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
                    if ($proc -and -not $proc.HasExited) {
                        Stop-Process -Id $pid -Force -ErrorAction Stop
                        Write-Host "  [停止] $name (PID: $pid)" -ForegroundColor Red
                        $stopped++
                    }
                } catch { }
            }
        } else {
            Write-Host "  [跳过] $name (端口 $port 无进程)" -ForegroundColor Gray
        }
    } catch {
        Write-Host "  [错误] $name : $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "  共停止 $stopped 个进程" -ForegroundColor $(if ($stopped -gt 0) { "Green" } else { "Gray" })
Write-Host ""
