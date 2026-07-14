<#
.SYNOPSIS
Yunxi System - Start All Modules
.DESCRIPTION
Start all 13 modules (M0-M12) in dependency order
#>

$ErrorActionPreference = "Continue"
$BaseDir = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $BaseDir "logs"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$Modules = New-Object System.Collections.ArrayList
$null = $Modules.Add(@{Name="M5-tide-memory"; Port=8005; Path="M5-tide-memory"; Cmd="python src/main.py"; LogFile="m5.log"})
$null = $Modules.Add(@{Name="M2-skills-cluster"; Port=8002; Path="M2-skills-cluster"; Cmd="python start_server.py"; LogFile="m2.log"})
$null = $Modules.Add(@{Name="M4-scene-engine"; Port=8004; Path="m4-scene-engine"; Cmd="python -m src.main"; LogFile="m4.log"})
$null = $Modules.Add(@{Name="M3-edge-cloud"; Port=8003; Path="M3-edge-cloud"; Cmd="python server.py"; LogFile="m3.log"})
$null = $Modules.Add(@{Name="M6-hardware"; Port=8006; Path="M6-hardware-peripheral"; Cmd="python server.py"; LogFile="m6.log"})
$null = $Modules.Add(@{Name="M1-agent-hub"; Port=8001; Path="M1-agent-hub"; Cmd="python server.py"; LogFile="m1.log"})
$null = $Modules.Add(@{Name="M7-workflow"; Port=8007; Path="M7-workflow-builder"; Cmd="python -m src.main"; LogFile="m7.log"})
$null = $Modules.Add(@{Name="M8-control-tower"; Port=8008; Path="M8-control-tower"; Cmd="python -m backend.main"; LogFile="m8.log"})
$null = $Modules.Add(@{Name="M9-dev-workshop"; Port=8009; Path="M9-dev-workshop"; Cmd="python backend/main.py"; LogFile="m9.log"})
$null = $Modules.Add(@{Name="M10-system-guard"; Port=8010; Path="M10-system-guard"; Cmd="python server.py"; LogFile="m10.log"})
$null = $Modules.Add(@{Name="M0-principal-console"; Port=8000; Path="M0-principal-console"; Cmd="python -m src.main"; LogFile="m0.log"})
$null = $Modules.Add(@{Name="M11-mcp-bus"; Port=8011; Path="M11-mcp-bus"; Cmd="python -m src.main"; LogFile="m11.log"})
$null = $Modules.Add(@{Name="M12-security-shield"; Port=8012; Path="M12-security-shield"; Cmd="python -m backend.main"; LogFile="m12.log"})

$Processes = @()

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  Yunxi System Starting..." -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

$successCount = 0
$failCount = 0

foreach ($mod in $Modules) {
    $modPath = Join-Path $BaseDir $mod.Path
    $logPath = Join-Path $LogDir $mod.LogFile

    if (-not (Test-Path $modPath)) {
        Write-Host "  [SKIP] $($mod.Name) - directory not found" -ForegroundColor Yellow
        continue
    }

    Write-Host "  [START] $($mod.Name) (port $($mod.Port))..." -ForegroundColor Green

    try {
        $process = Start-Process -FilePath "powershell" `
            -ArgumentList "-NoExit", "-Command", "cd '$modPath'; $($mod.Cmd) 2>&1 | Tee-Object -FilePath '$logPath'" `
            -PassThru -WindowStyle Normal

        $Processes += @{ Name = $mod.Name; Process = $process; Port = $mod.Port }

        $timeout = 60
        $elapsed = 0
        $ready = $false
        while ($elapsed -lt $timeout) {
            try {
                $tcp = New-Object System.Net.Sockets.TcpClient
                $tcp.Connect("127.0.0.1", $mod.Port)
                $tcp.Close()
                $ready = $true
                break
            } catch {
                Start-Sleep -Milliseconds 500
                $elapsed += 0.5
            }
        }

        if ($ready) {
            Write-Host "  [READY] $($mod.Name) started OK" -ForegroundColor Green
            $successCount++
        } else {
            Write-Host "  [TIMEOUT] $($mod.Name) - check log: $logPath" -ForegroundColor Yellow
            $failCount++
        }
    } catch {
        Write-Host "  [FAIL] $($mod.Name) error: $($_.Exception.Message)" -ForegroundColor Red
        $failCount++
    }
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  Done. Success $successCount / $($Modules.Count)" -ForegroundColor $(if ($failCount -eq 0) { "Green" } else { "Yellow" })
Write-Host "  M0 console: http://localhost:8000" -ForegroundColor White
Write-Host "  M8 control: http://localhost:8008" -ForegroundColor White
Write-Host "  M9 workshop: http://localhost:8009" -ForegroundColor White
Write-Host "  M11 mcp-bus: http://localhost:8011" -ForegroundColor White
Write-Host "  M12 security: http://localhost:8012" -ForegroundColor White
Write-Host "  Logs: $LogDir" -ForegroundColor Gray
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Press Ctrl+C to stop all modules" -ForegroundColor Gray
Write-Host ""

try {
    while ($true) { Start-Sleep -Seconds 5 }
} finally {
    Write-Host ""
    Write-Host "  Stopping all modules..." -ForegroundColor Yellow
    foreach ($p in $Processes) {
        if (-not $p.Process.HasExited) {
            try {
                Stop-Process -Id $p.Process.Id -Force -ErrorAction SilentlyContinue
                Write-Host "  [STOP] $($p.Name)" -ForegroundColor Red
            } catch { }
        }
    }
    Write-Host ""
    Write-Host "  All modules stopped" -ForegroundColor Green
    Write-Host ""
}
