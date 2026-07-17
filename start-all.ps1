# Yunxi System - Start All Modules
# Usage: powershell -ExecutionPolicy Bypass -File start-all.ps1

param(
    [switch]$WaitForHealth,
    [int]$HealthTimeout = 180
)

$ErrorActionPreference = "Continue"
$ProjectRoot = $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = Get-Location }
$EnvFile = Join-Path $ProjectRoot "config\yunxi.env"

# Load env
Write-Host "`n[0] Loading: $EnvFile" -ForegroundColor Cyan
if (Test-Path $EnvFile) {
    Get-Content $EnvFile -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -and !$line.StartsWith("#") -and $line -match "^([A-Za-z_0-9]+)=(.*)$") {
            $key = $Matches[1]
            $val = $Matches[2]
            if ($val.Length -gt 0) {
                [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
            }
        }
    }
    Write-Host "  OK" -ForegroundColor Green
}

# Module definitions
$M = @(
    @{N="Gateway";         D="API-Gateway";           C="python server.py";       P=$env:GATEWAY_PORT; O=1}
    @{N="M5 TideMemory";  D="M5-tide-memory";       C="python server.py";       P=$env:M5_PORT;  O=1}
    @{N="M11 MCP Bus";    D="M11-mcp-bus";          C="python server.py";       P=$env:M11_PORT; O=1}
    @{N="M12 Security";   D="M12-security-shield";  C="python server.py";       P=$env:M12_PORT; O=1}
    @{N="M1 AgentHub";    D="M1-agent-hub";         C="python server.py";       P=$env:M1_PORT;  O=2}
    @{N="M4 SceneEngine";  D="m4-scene-engine";      C="python -m src";          P=$env:M4_PORT;  O=2}
    @{N="M8 ControlTower"; D="M8-control-tower";     C="python -m backend";      P=$env:M8_PORT;  O=2}
    @{N="M2 SkillCluster"; D="M2-skills-cluster";    C="python start_server.py";P=$env:M2_PORT;  O=3}
    @{N="M3 EdgeCloud";    D="M3-edge-cloud";        C="python server.py";       P=$env:M3_PORT;  O=3}
    @{N="M6 Hardware";      D="M6-hardware-peripheral";C="python server.py";      P=$env:M6_PORT;  O=3}
    @{N="M7 Workflow";      D="M7-workflow-builder";  C="python server.py";       P=$env:M7_PORT;  O=3}
    @{N="M9 DevWorkshop";   D="M9-dev-workshop";      C="python backend/main.py";P=$env:M9_PORT;  O=3}
    @{N="M10 SystemGuard";  D="M10-system-guard";     C="python server.py";       P=$env:M10_PORT; O=3}
    @{N="M0 Console";      D="M0-principal-console";  C="python server.py";       P=$env:M0_PORT;  O=4}
)

Write-Host "`n========================================" -ForegroundColor White
Write-Host "  Yunxi System - Start All 14 Modules" -ForegroundColor White
Write-Host "========================================`n" -ForegroundColor White

$Results = @{}
$Pids = @{}

foreach ($Order in (1..4)) {
    $Batch = $M | Where-Object { $_.O -eq $Order }
    foreach ($Mod in $Batch) {
        $Idx = $M.IndexOf($Mod)
        $Tag = "[{0:D2}] {1}" -f $Idx, $Mod.N
        Write-Host "$Tag ... " -NoNewline -ForegroundColor Cyan

        $Dir = Join-Path $ProjectRoot $Mod.D
        if (-not (Test-Path $Dir)) {
            Write-Host "SKIP (dir not found)" -ForegroundColor Yellow
            $Results[$Mod.N] = $false
            continue
        }

        $Port = [int]$Mod.P
        $Occupied = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
        if ($Occupied) {
            Write-Host "SKIP (port $Port in use)" -ForegroundColor Yellow
            $Results[$Mod.N] = $false
            continue
        }

        $Proc = Start-Process -FilePath "python" -ArgumentList $Mod.C -WorkingDirectory $Dir -WindowStyle Minimized -PassThru -ErrorAction SilentlyContinue
        if ($Proc) {
            Write-Host "PID=$($Proc.Id) Port=$Port" -ForegroundColor Green
            $Results[$Mod.N] = $true
            $Pids[$Mod.D] = $Proc.Id
        } else {
            Write-Host "FAIL" -ForegroundColor Red
            $Results[$Mod.N] = $false
        }
        Start-Sleep -Milliseconds 300
    }
    if ($Order -lt 4) { Start-Sleep -Seconds 2 }
}

# Health check
if ($WaitForHealth) {
    Write-Host "`n[Health Check] Waiting (timeout ${HealthTimeout}s)..." -ForegroundColor Cyan
    $Deadline = [datetime]::Now.AddSeconds($HealthTimeout)
    $AllUp = $false
    while (-not $AllUp -and [datetime]::Now -lt $Deadline) {
        Start-Sleep -Seconds 3
        $AllUp = $true
        foreach ($Mod in $M) {
            $Port = [int]$Mod.P
            try {
                $Tcp = [System.Net.Sockets.TcpClient]::new()
                $Task = $Tcp.ConnectAsync("127.0.0.1", $Port)
                $Task.Wait(1000) | Out-Null
                if ($Task.IsCompleted -and !$Task.IsFaulted) { $Tcp.Close() }
                else { $AllUp = $false }
            } catch { $AllUp = $false }
        }
    }
    if ($AllUp) { Write-Host "  ALL HEALTHY" -ForegroundColor Green }
    else { Write-Host "  TIMEOUT" -ForegroundColor Yellow }
}

# Summary
Write-Host "`n========================================" -ForegroundColor White
$Ok = 0
foreach ($Mod in $M) {
    $R = $Results[$Mod.N]
    if ($R) {
        $Ok++; $Color = "Green"; $S = "OK"
    } else {
        $Color = "Red"; $S = "FAIL"
    }
    Write-Host ("  {0,-20} Port={1,-5} {2}" -f $Mod.N, $Mod.P, $S) -ForegroundColor $Color
}
Write-Host ("`n  Total: {0}/14 started" -f $Ok) -ForegroundColor $(if ($Ok -eq 14) {"Green"} else {"Yellow"})

# Save PIDs
if ($Pids.Count -gt 0) {
    $PidFile = Join-Path $ProjectRoot ".start-all-pids.json"
    $Pids | ConvertTo-Json | Set-Content $PidFile -Encoding UTF8
    Write-Host "`n  PID file: .start-all-pids.json" -ForegroundColor DarkGray
    Write-Host "  Stop: .\stop-all.ps1`n" -ForegroundColor DarkGray
}
