<#
.SYNOPSIS
    云汐系统 - 全模块停止脚本
.DESCRIPTION
    读取 .start-all-pids.json 中保存的进程 PID 并终止。
#>

$ProjectRoot = $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = Get-Location }
$PidFile = Join-Path $ProjectRoot ".start-all-pids.json"

if (-not (Test-Path $PidFile)) {
    Write-Host "PID 文件未找到: $PidFile" -ForegroundColor Yellow
    Write-Host "尝试通过端口查找进程..." -ForegroundColor Yellow
    
    $Ports = @(8080) + (8000..8012)
    foreach ($Port in $Ports) {
        $Conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($Conn) {
            foreach ($C in $Conn) {
                try {
                    Stop-Process -Id $C.OwningProcess -Force -ErrorAction SilentlyContinue
                    Write-Host "  停止 Port=$Port PID=$($C.OwningProcess)" -ForegroundColor Green
                } catch {}
            }
        }
    }
    return
}

$Pids = Get-Content $PidFile -Encoding UTF8 | ConvertFrom-Json
$Killed = 0
foreach ($Key in $Pids.PSObject.Properties.Name) {
    $Pid = $Pids.$Key
    try {
        $Proc = Get-Process -Id $Pid -ErrorAction SilentlyContinue
        if ($Proc) {
            Stop-Process -Id $Pid -Force
            Write-Host "  停止 $Key (PID=$Pid)" -ForegroundColor Green
            $Killed++
        }
    } catch {
        Write-Host "  $Key (PID=$Pid) 已不存在" -ForegroundColor DarkGray
    }
}
Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "`n  共停止 $Killed 个进程" -ForegroundColor Cyan
