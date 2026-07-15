<#
.SYNOPSIS
    启动云汐边缘节点（选择性运行部分模块）

.DESCRIPTION
    启动一个云汐边缘节点，可选择运行指定模块。
    边缘节点会自动向主节点注册并维持心跳。

.PARAMETER NodeName
    节点显示名称（默认 "边缘节点1"）

.PARAMETER NodeRole
    节点角色，固定为 edge

.PARAMETER Modules
    本节点运行的模块列表，如 "M4", "M5"

.PARAMETER PrimaryHost
    主节点地址（默认 "localhost"）

.PARAMETER PrimaryPort
    主节点 API 端口（默认 8080）

.PARAMETER NodeId
    节点唯一标识（默认自动生成）

.EXAMPLE
    .\start-edge-node.ps1 -NodeName "边缘节点1" -Modules @("M4", "M5")
    .\start-edge-node.ps1 -NodeName "GPU节点" -Modules @("M9") -PrimaryHost "192.168.1.100"
#>

param(
    [string]$NodeName = "边缘节点1",
    [string]$NodeRole = "edge",
    [string[]]$Modules = @("M4", "M5"),
    [string]$PrimaryHost = "localhost",
    [int]$PrimaryPort = 8080,
    [string]$NodeId = ""
)

# -------------------------------------------------------------------
# 配置环境变量
# -------------------------------------------------------------------

# 生成节点 ID（如果未指定）
if (-not $NodeId) {
    $NodeId = [guid]::NewGuid().ToString("N").Substring(0, 8)
}

$env:YUNXI_NODE_ID = $NodeId
$env:YUNXI_NODE_ROLE = $NodeRole
$env:YUNXI_NODE_NAME = $NodeName
$env:YUNXI_PEER_NODES = "[{`"id`":`"primary`",`"host`":`"$PrimaryHost`",`"port`":$PrimaryPort}]"
$env:YUNXI_NODE_MODULES = ($Modules | ConvertTo-Json -Compress)

# 节点 API 端口（避免与主节点冲突）
$env:YUNXI_NODE_API_PORT = "8081"

# 项目根目录
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  云汐边缘节点启动器" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  节点 ID:     $NodeId" -ForegroundColor Yellow
Write-Host "  节点名称:   $NodeName" -ForegroundColor Yellow
Write-Host "  运行模块:   $($Modules -join ', ')" -ForegroundColor Yellow
Write-Host "  主节点地址: ${PrimaryHost}:${PrimaryPort}" -ForegroundColor Yellow
Write-Host "  项目根目录: $projectRoot" -ForegroundColor Yellow
Write-Host ""

# -------------------------------------------------------------------
# 模块启动映射表
# -------------------------------------------------------------------

$moduleStartMap = @{
    "M0"  = @{ Dir = "M0-principal-console"; Script = ""; Port = 8080 }
    "M1"  = @{ Dir = "M1-agent-hub";         Script = ""; Port = 8001 }
    "M2"  = @{ Dir = "M2-skills-cluster";     Script = ""; Port = 8002 }
    "M3"  = @{ Dir = "M3-edge-cloud";         Script = ""; Port = 8003 }
    "M4"  = @{ Dir = "m4-scene-engine";       Script = ""; Port = 8004 }
    "M5"  = @{ Dir = "M5-tide-memory";        Script = ""; Port = 8005 }
    "M6"  = @{ Dir = "M6-hardware-peripheral"; Script = ""; Port = 8006 }
    "M7"  = @{ Dir = "M7-workflow-builder";   Script = ""; Port = 8007 }
    "M8"  = @{ Dir = "M8-control-tower";      Script = "backend\run.py"; Port = 8008 }
    "M9"  = @{ Dir = "M9-dev-workshop";        Script = ""; Port = 8009 }
    "M10" = @{ Dir = "M10-system-guard";      Script = ""; Port = 8010 }
    "M11" = @{ Dir = "M11-mcp-bus";           Script = ""; Port = 8011 }
    "M12" = @{ Dir = "M12-security-shield";   Script = ""; Port = 8012 }
}

# -------------------------------------------------------------------
# 逐个启动模块
# -------------------------------------------------------------------

$startedProcesses = @{}

foreach ($m in $Modules) {
    $mUpper = $m.ToUpper()

    if ($moduleStartMap.ContainsKey($mUpper)) {
        $moduleInfo = $moduleStartMap[$mUpper]
        $moduleDir = Join-Path $projectRoot $moduleInfo.Dir

        if (Test-Path $moduleDir) {
            Write-Host "[启动] $mUpper → $moduleDir" -ForegroundColor Green

            if ($moduleInfo.Script) {
                $scriptPath = Join-Path $moduleDir $moduleInfo.Script
                $proc = Start-Process -FilePath "python" -ArgumentList $scriptPath `
                    -WorkingDirectory $moduleDir `
                    -PassThru `
                    -WindowStyle Minimized
            } else {
                # 尝试查找 main.py 或 run.py
                $mainPy = Join-Path $moduleDir "main.py"
                $runPy = Join-Path $moduleDir "run.py"

                if (Test-Path $mainPy) {
                    $proc = Start-Process -FilePath "python" -ArgumentList $mainPy `
                        -WorkingDirectory $moduleDir `
                        -PassThru `
                        -WindowStyle Minimized
                } elseif (Test-Path $runPy) {
                    $proc = Start-Process -FilePath "python" -ArgumentList $runPy `
                        -WorkingDirectory $moduleDir `
                        -PassThru `
                        -WindowStyle Minimized
                } else {
                    Write-Host "  [警告] 未找到启动脚本 (main.py / run.py): $moduleDir" -ForegroundColor DarkYellow
                    continue
                }
            }

            $startedProcesses[$mUpper] = $proc.Id
            Start-Sleep -Seconds 2
        } else {
            Write-Host "  [跳过] 目录不存在: $moduleDir" -ForegroundColor DarkYellow
        }
    } else {
        Write-Host "  [跳过] 未知模块: $mUpper" -ForegroundColor DarkYellow
    }
}

# -------------------------------------------------------------------
# 输出启动摘要
# -------------------------------------------------------------------

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  启动完成" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  已启动进程:" -ForegroundColor Green
foreach ($key in $startedProcesses.Keys) {
    Write-Host "    $key → PID: $($startedProcesses[$key])" -ForegroundColor Green
}
Write-Host ""
Write-Host "  集群管理 API: http://localhost:$($env:YUNXI_NODE_API_PORT)/api/v1/cluster/health" -ForegroundColor Yellow
Write-Host ""

# -------------------------------------------------------------------
# 保持运行（按 Ctrl+C 退出）
# -------------------------------------------------------------------

Write-Host "按 Ctrl+C 停止所有模块..." -ForegroundColor Gray

try {
    while ($true) {
        Start-Sleep -Seconds 5
    }
} finally {
    Write-Host ""
    Write-Host "正在停止所有模块..." -ForegroundColor Yellow
    foreach ($key in $startedProcesses.Keys) {
        $pid = $startedProcesses[$key]
        try {
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            Write-Host "  [停止] $key (PID: $pid)" -ForegroundColor Gray
        } catch {
            Write-Host "  [失败] 停止 $key 失败: $_" -ForegroundColor Red
        }
    }
    Write-Host "边缘节点已关闭" -ForegroundColor Yellow
}
