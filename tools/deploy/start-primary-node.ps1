<#
.SYNOPSIS
    启动云汐主节点（运行全部 13 模块 + 集群管理）

.DESCRIPTION
    启动云汐主节点，自动运行所有模块（M0-M12）并启用集群注册中心。
    主节点作为集群的核心，负责节点注册、心跳管理和消息中转。

.EXAMPLE
    .\start-primary-node.ps1
    .\start-primary-node.ps1 -NodeId "main-001" -NodeName "云汐主节点-生产"
#>

param(
    [string]$NodeId = "",
    [string]$NodeName = "云汐主节点",
    [string]$ClusterId = "yunxi-default",
    [int]$ApiPort = 8080
)

# -------------------------------------------------------------------
# 配置环境变量
# -------------------------------------------------------------------

if (-not $NodeId) {
    $NodeId = [guid]::NewGuid().ToString("N").Substring(0, 8)
}

$env:YUNXI_NODE_ID = $NodeId
$env:YUNXI_NODE_ROLE = "primary"
$env:YUNXI_NODE_NAME = $NodeName
$env:YUNXI_CLUSTER_ID = $ClusterId
$env:YUNXI_NODE_API_PORT = "$ApiPort"
$env:YUNXI_NODE_MODULES = '["M0","M1","M2","M3","M4","M5","M6","M7","M8","M9","M10","M11","M12"]'

# 项目根目录
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  云汐主节点启动器" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  节点 ID:     $NodeId" -ForegroundColor Yellow
Write-Host "  节点名称:   $NodeName" -ForegroundColor Yellow
Write-Host "  集群 ID:     $ClusterId" -ForegroundColor Yellow
Write-Host "  API 端口:    $ApiPort" -ForegroundColor Yellow
Write-Host "  项目根目录: $projectRoot" -ForegroundColor Yellow
Write-Host ""
Write-Host "  运行模块:   M0, M1, M2, M3, M4, M5, M6, M7, M8, M9, M10, M11, M12" -ForegroundColor Green
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

$allModules = @("M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10", "M11", "M12")
$startedProcesses = @{}

# -------------------------------------------------------------------
# 逐个启动全部模块
# -------------------------------------------------------------------

foreach ($m in $allModules) {
    $moduleInfo = $moduleStartMap[$m]
    $moduleDir = Join-Path $projectRoot $moduleInfo.Dir

    if (Test-Path $moduleDir) {
        Write-Host "[启动] $m → $moduleDir" -ForegroundColor Green

        if ($moduleInfo.Script) {
            $scriptPath = Join-Path $moduleDir $moduleInfo.Script
            $proc = Start-Process -FilePath "python" -ArgumentList $scriptPath `
                -WorkingDirectory $moduleDir `
                -PassThru `
                -WindowStyle Minimized
        } else {
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
                Write-Host "  [警告] 未找到启动脚本: $moduleDir" -ForegroundColor DarkYellow
                continue
            }
        }

        $startedProcesses[$m] = $proc.Id
        Start-Sleep -Seconds 2
    } else {
        Write-Host "  [跳过] 目录不存在: $moduleDir" -ForegroundColor DarkYellow
    }
}

# -------------------------------------------------------------------
# 输出启动摘要
# -------------------------------------------------------------------

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  主节点启动完成" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  已启动进程:" -ForegroundColor Green
foreach ($key in $startedProcesses.Keys) {
    Write-Host "    $key → PID: $($startedProcesses[$key])" -ForegroundColor Green
}
Write-Host ""
Write-Host "  集群管理 API:" -ForegroundColor Yellow
Write-Host "    健康状态:   http://localhost:${ApiPort}/api/v1/cluster/health" -ForegroundColor Yellow
Write-Host "    节点列表:   http://localhost:${ApiPort}/api/v1/cluster/nodes" -ForegroundColor Yellow
Write-Host "    API 文档:   http://localhost:${ApiPort}/docs" -ForegroundColor Yellow
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
    Write-Host "主节点已关闭" -ForegroundColor Yellow
}
