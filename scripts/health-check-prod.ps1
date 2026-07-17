<#
.SYNOPSIS
    云汐系统 - 生产环境健康检查脚本
.DESCRIPTION
    全面检查系统健康状态，包括：
    - 所有模块健康状态（HTTP 接口检查）
    - 数据库连接检查
    - Redis 连接检查
    - 磁盘空间检查
    - 内存使用检查
    - CPU 负载检查
    - 输出统一格式的健康报告
    - 异常时返回非零退出码（便于监控）
.PARAMETER Module
    只检查指定模块（名称或端口）
.PARAMETER OutputFormat
    输出格式: text, json, brief
.PARAMETER Timeout
    单个检查超时时间（秒）
.PARAMETER WarnOnly
    只输出警告，不返回非零退出码
.PARAMETER Quiet
    静默模式，只在异常时输出
.EXAMPLE
    .\health-check-prod.ps1
    完整健康检查
.EXAMPLE
    .\health-check-prod.ps1 -Module "M1"
    只检查 M1 模块
.EXAMPLE
    .\health-check-prod.ps1 -OutputFormat json
    输出 JSON 格式报告
.EXAMPLE
    .\health-check-prod.ps1 -WarnOnly
    只告警，不返回非零退出码
.NOTES
    用于监控系统时，可通过退出码判断健康状态：
    0 = 全部健康
    1 = 有警告
    2 = 有严重错误
#>

param(
    [string]$Module = "",
    [ValidateSet("text", "json", "brief")]
    [string]$OutputFormat = "text",
    [int]$Timeout = 5,
    [switch]$WarnOnly,
    [switch]$Quiet
)

# ============================================================
# 初始化
# ============================================================

$ErrorActionPreference = "SilentlyContinue"
$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Get-Location }
# 脚本在 scripts/ 子目录下，项目根目录是父目录
$ProjectRoot = Split-Path $ScriptDir -Parent

$Script:CheckResults = [System.Collections.ArrayList]::new()
$Script:OverallStatus = "healthy"  # healthy, warning, critical

# 模块定义
$Modules = @(
    @{Name = "Gateway";        Dir = "API-Gateway";            Port = 8080; HealthPath = "/health" },
    @{Name = "M0 Console";     Dir = "M0-principal-console";   Port = 8000; HealthPath = "/health" },
    @{Name = "M1 AgentHub";    Dir = "M1-agent-hub";           Port = 8001; HealthPath = "/health" },
    @{Name = "M2 SkillCluster";Dir = "M2-skills-cluster";      Port = 8002; HealthPath = "/api/health" },
    @{Name = "M3 EdgeCloud";   Dir = "M3-edge-cloud";          Port = 8003; HealthPath = "/api/health" },
    @{Name = "M4 SceneEngine"; Dir = "m4-scene-engine";        Port = 8004; HealthPath = "/health" },
    @{Name = "M5 TideMemory";  Dir = "M5-tide-memory";         Port = 8005; HealthPath = "/health" },
    @{Name = "M6 Hardware";    Dir = "M6-hardware-peripheral"; Port = 8006; HealthPath = "/api/v1/health" },
    @{Name = "M7 Workflow";    Dir = "M7-workflow-builder";    Port = 8007; HealthPath = "/health" },
    @{Name = "M8 ControlTower";Dir = "M8-control-tower";       Port = 8008; HealthPath = "/api/health" },
    @{Name = "M9 DevWorkshop"; Dir = "M9-dev-workshop";        Port = 8009; HealthPath = "/health" },
    @{Name = "M10 SystemGuard";Dir = "M10-system-guard";       Port = 8010; HealthPath = "/health" },
    @{Name = "M11 MCP Bus";    Dir = "M11-mcp-bus";            Port = 8011; HealthPath = "/health" },
    @{Name = "M12 Security";   Dir = "M12-security-shield";    Port = 8012; HealthPath = "/health" }
)

# 阈值配置
$Thresholds = @{
    DiskWarningPercent     = 20    # 低于 20% 警告
    DiskCriticalPercent    = 10    # 低于 10% 严重
    MemoryWarningPercent   = 80    # 高于 80% 警告
    MemoryCriticalPercent  = 90    # 高于 90% 严重
    CpuWarningPercent      = 80    # 高于 80% 警告
    CpuCriticalPercent     = 95    # 高于 95% 严重
}

# ============================================================
# 工具函数
# ============================================================

function Add-CheckResult {
    param(
        [string]$Category,
        [string]$Name,
        [string]$Status,
        [string]$Message = "",
        $Value = $null
    )

    $result = [PSCustomObject]@{
        Category = $Category
        Name     = $Name
        Status   = $Status    # healthy, warning, critical, unknown
        Message  = $Message
        Value    = $Value
        Time     = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    }

    [void]$Script:CheckResults.Add($result)

    # 更新整体状态
    if ($Status -eq "critical" -and $Script:OverallStatus -ne "critical") {
        $Script:OverallStatus = "critical"
    }
    elseif ($Status -eq "warning" -and $Script:OverallStatus -eq "healthy") {
        $Script:OverallStatus = "warning"
    }

    return $result
}

function Get-StatusColor {
    param([string]$Status)
    switch ($Status) {
        "healthy"  { return "Green" }
        "warning"  { return "Yellow" }
        "critical" { return "Red" }
        default    { return "Gray" }
    }
}

function Get-StatusIcon {
    param([string]$Status)
    switch ($Status) {
        "healthy"  { return "[OK]" }
        "warning"  { return "[WARN]" }
        "critical" { return "[CRIT]" }
        default    { return "[?]" }
    }
}

# ============================================================
# 检查 1: 模块健康状态
# ============================================================

function Test-ModuleHealth {
    $category = "Service"

    foreach ($mod in $Modules) {
        # 如果指定了模块名，过滤
        if (-not [string]::IsNullOrEmpty($Module)) {
            if ($mod.Name -notmatch $Module -and $mod.Port -ne $Module) {
                continue
            }
        }

        $url = "http://localhost:$($mod.Port)$($mod.HealthPath)"

        try {
            $response = Invoke-RestMethod -Uri $url -TimeoutSec $Timeout -ErrorAction Stop

            # 判断健康状态
            $isHealthy = $false
            $statusText = ""

            if ($response.PSObject.Properties.Name -contains "status") {
                $statusText = $response.status
                $isHealthy = ($response.status -eq "ok" -or $response.status -eq "healthy")
            }
            elseif ($response.PSObject.Properties.Name -contains "code") {
                $isHealthy = ($response.code -eq 0 -or $response.code -eq 200)
                $statusText = "code=$($response.code)"
            }
            elseif ($response -is [string]) {
                $isHealthy = ($response -eq "ok" -or $response -eq "healthy")
                $statusText = $response
            }
            else {
                # 能返回响应就算健康
                $isHealthy = $true
                $statusText = "response ok"
            }

            if ($isHealthy) {
                Add-CheckResult -Category $category -Name $mod.Name `
                    -Status "healthy" -Message "运行正常" -Value $statusText
            }
            else {
                Add-CheckResult -Category $category -Name $mod.Name `
                    -Status "warning" -Message "状态异常" -Value $statusText
            }
        }
        catch {
            $errMsg = $_.Exception.Message
            if ($errMsg -match "actively refused" -or $errMsg -match "No connection") {
                Add-CheckResult -Category $category -Name $mod.Name `
                    -Status "critical" -Message "服务未启动或端口未监听" -Value "connection refused"
            }
            elseif ($errMsg -match "timed out" -or $errMsg -match "timeout") {
                Add-CheckResult -Category $category -Name $mod.Name `
                    -Status "warning" -Message "响应超时" -Value "timeout"
            }
            else {
                Add-CheckResult -Category $category -Name $mod.Name `
                    -Status "warning" -Message "检查异常" -Value $errMsg
            }
        }
    }
}

# ============================================================
# 检查 2: Redis 连接
# ============================================================

function Test-RedisConnection {
    $category = "Infrastructure"
    $name = "Redis"

    try {
        # 尝试通过 TCP 连接检查 Redis
        $redisPort = 6379
        $tcpClient = New-Object System.Net.Sockets.TcpClient
        $connectTask = $tcpClient.ConnectAsync("localhost", $redisPort)
        $wait = $connectTask.Wait([TimeSpan]::FromSeconds($Timeout))

        if ($wait -and $connectTask.IsCompleted -and -not $connectTask.IsFaulted) {
            $tcpClient.Close()
            Add-CheckResult -Category $category -Name $name `
                -Status "healthy" -Message "Redis 连接正常" -Value "port $redisPort open"
        }
        else {
            Add-CheckResult -Category $category -Name $name `
                -Status "critical" -Message "Redis 连接失败" -Value "connection refused"
        }
    }
    catch {
        Add-CheckResult -Category $category -Name $name `
            -Status "critical" -Message "Redis 检查异常" -Value $_.Exception.Message
    }
}

# ============================================================
# 检查 3: 数据库检查
# ============================================================

function Test-Database {
    $category = "Infrastructure"
    $name = "Database (SQLite)"

    try {
        $dataDir = Join-Path $ProjectRoot "data"

        if (-not (Test-Path $dataDir)) {
            Add-CheckResult -Category $category -Name $name `
                -Status "warning" -Message "数据目录不存在" -Value $dataDir
            return
        }

        $dbFiles = Get-ChildItem $dataDir -Filter "*.db" -ErrorAction SilentlyContinue

        if ($dbFiles -and $dbFiles.Count -gt 0) {
            $totalSize = ($dbFiles | Measure-Object -Property Length -Sum).Sum
            $totalSizeMB = [math]::Round($totalSize / 1MB, 2)
            Add-CheckResult -Category $category -Name $name `
                -Status "healthy" -Message "$($dbFiles.Count) 个数据库文件" -Value "${totalSizeMB} MB"
        }
        else {
            Add-CheckResult -Category $category -Name $name `
                -Status "warning" -Message "未找到数据库文件（可能尚未初始化）" -Value "no .db files"
        }
    }
    catch {
        Add-CheckResult -Category $category -Name $name `
            -Status "warning" -Message "数据库检查异常" -Value $_.Exception.Message
    }
}

# ============================================================
# 检查 4: 磁盘空间
# ============================================================

function Test-DiskSpace {
    $category = "System"
    $name = "Disk Space"

    try {
        $drive = (Get-Item $ProjectRoot).PSDrive
        $freeGB = [math]::Round($drive.Free / 1GB, 2)
        $totalGB = [math]::Round(($drive.Used + $drive.Free) / 1GB, 2)
        $freePercent = [math]::Round(($drive.Free / ($drive.Used + $drive.Free)) * 100, 1)

        $value = "${freeGB}GB / ${totalGB}GB (${freePercent}% free)"

        if ($freePercent -le $Thresholds.DiskCriticalPercent) {
            Add-CheckResult -Category $category -Name $name `
                -Status "critical" -Message "磁盘空间严重不足" -Value $value
        }
        elseif ($freePercent -le $Thresholds.DiskWarningPercent) {
            Add-CheckResult -Category $category -Name $name `
                -Status "warning" -Message "磁盘空间不足" -Value $value
        }
        else {
            Add-CheckResult -Category $category -Name $name `
                -Status "healthy" -Message "磁盘空间充足" -Value $value
        }
    }
    catch {
        Add-CheckResult -Category $category -Name $name `
            -Status "unknown" -Message "无法检查磁盘空间" -Value $_.Exception.Message
    }
}

# ============================================================
# 检查 5: 内存使用
# ============================================================

function Test-MemoryUsage {
    $category = "System"
    $name = "Memory"

    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
        $freeGB = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
        $usedGB = [math]::Round($totalGB - $freeGB, 2)
        $usedPercent = [math]::Round((($totalGB - $freeGB) / $totalGB) * 100, 1)

        $value = "${usedGB}GB / ${totalGB}GB (${usedPercent}% used)"

        if ($usedPercent -ge $Thresholds.MemoryCriticalPercent) {
            Add-CheckResult -Category $category -Name $name `
                -Status "critical" -Message "内存使用率过高" -Value $value
        }
        elseif ($usedPercent -ge $Thresholds.MemoryWarningPercent) {
            Add-CheckResult -Category $category -Name $name `
                -Status "warning" -Message "内存使用率较高" -Value $value
        }
        else {
            Add-CheckResult -Category $category -Name $name `
                -Status "healthy" -Message "内存使用正常" -Value $value
        }
    }
    catch {
        Add-CheckResult -Category $category -Name $name `
            -Status "unknown" -Message "无法检查内存" -Value $_.Exception.Message
    }
}

# ============================================================
# 检查 6: CPU 负载
# ============================================================

function Test-CpuUsage {
    $category = "System"
    $name = "CPU"

    try {
        $cpu = Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average
        $cpuUsage = [math]::Round($cpu.Average, 1)

        $value = "${cpuUsage}%"

        if ($cpuUsage -ge $Thresholds.CpuCriticalPercent) {
            Add-CheckResult -Category $category -Name $name `
                -Status "critical" -Message "CPU 负载过高" -Value $value
        }
        elseif ($cpuUsage -ge $Thresholds.CpuWarningPercent) {
            Add-CheckResult -Category $category -Name $name `
                -Status "warning" -Message "CPU 负载较高" -Value $value
        }
        else {
            Add-CheckResult -Category $category -Name $name `
                -Status "healthy" -Message "CPU 负载正常" -Value $value
        }
    }
    catch {
        Add-CheckResult -Category $category -Name $name `
            -Status "unknown" -Message "无法检查 CPU" -Value $_.Exception.Message
    }
}

# ============================================================
# 输出报告
# ============================================================

function Show-ReportText {
    if ($Quiet -and $Script:OverallStatus -eq "healthy") {
        return
    }

    Write-Host ""
    Write-Host "=========================================" -ForegroundColor Cyan
    Write-Host "  云汐系统健康检查报告" -ForegroundColor Cyan
    Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Gray
    Write-Host "=========================================" -ForegroundColor Cyan
    Write-Host ""

    # 按类别分组显示
    $categories = $Script:CheckResults | Group-Object Category | Sort-Object Name

    foreach ($cat in $categories) {
        Write-Host "[$($cat.Name)]" -ForegroundColor White
        Write-Host "--------"

        foreach ($item in $cat.Group) {
            $icon = Get-StatusIcon $item.Status
            $color = Get-StatusColor $item.Status

            $line = "$icon $($item.Name.PadRight(20)) $($item.Message)"
            if ($item.Value) {
                $line += " [$($item.Value)]"
            }

            Write-Host $line -ForegroundColor $color
        }
        Write-Host ""
    }

    # 统计
    $healthyCount = ($Script:CheckResults | Where-Object { $_.Status -eq "healthy" }).Count
    $warningCount = ($Script:CheckResults | Where-Object { $_.Status -eq "warning" }).Count
    $criticalCount = ($Script:CheckResults | Where-Object { $_.Status -eq "critical" }).Count
    $unknownCount = ($Script:CheckResults | Where-Object { $_.Status -eq "unknown" }).Count

    Write-Host "=========================================" -ForegroundColor Cyan
    Write-Host "  总计: $($Script:CheckResults.Count) 项检查"
    Write-Host "  正常: $healthyCount  " -ForegroundColor Green -NoNewline
    Write-Host "警告: $warningCount  " -ForegroundColor Yellow -NoNewline
    Write-Host "严重: $criticalCount  " -ForegroundColor Red -NoNewline
    Write-Host "未知: $unknownCount"
    Write-Host ""

    $statusColor = Get-StatusColor $Script:OverallStatus
    Write-Host "  总体状态: $($Script:OverallStatus.ToUpper())" -ForegroundColor $statusColor
    Write-Host "=========================================" -ForegroundColor Cyan
    Write-Host ""
}

function Show-ReportBrief {
    $healthyCount = ($Script:CheckResults | Where-Object { $_.Status -eq "healthy" }).Count
    $warningCount = ($Script:CheckResults | Where-Object { $_.Status -eq "warning" }).Count
    $criticalCount = ($Script:CheckResults | Where-Object { $_.Status -eq "critical" }).Count

    Write-Host ("HEALTH: {0} | Total: {1} OK: {2} WARN: {3} CRIT: {4}" -f `
        $Script:OverallStatus.ToUpper(), $Script:CheckResults.Count, `
        $healthyCount, $warningCount, $criticalCount)
}

function Show-ReportJson {
    $report = [PSCustomObject]@{
        timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
        status    = $Script:OverallStatus
        summary   = @{
            total    = $Script:CheckResults.Count
            healthy  = ($Script:CheckResults | Where-Object { $_.Status -eq "healthy" }).Count
            warning  = ($Script:CheckResults | Where-Object { $_.Status -eq "warning" }).Count
            critical = ($Script:CheckResults | Where-Object { $_.Status -eq "critical" }).Count
            unknown  = ($Script:CheckResults | Where-Object { $_.Status -eq "unknown" }).Count
        }
        checks    = $Script:CheckResults
    }

    $report | ConvertTo-Json -Depth 5
}

# ============================================================
# 主流程
# ============================================================

function Main {
    # 1. 模块健康检查
    Test-ModuleHealth

    # 如果指定了模块名，只检查模块，不进行系统检查
    if ([string]::IsNullOrEmpty($Module)) {
        # 2. Redis 检查
        Test-RedisConnection

        # 3. 数据库检查
        Test-Database

        # 4. 磁盘空间
        Test-DiskSpace

        # 5. 内存使用
        Test-MemoryUsage

        # 6. CPU 负载
        Test-CpuUsage
    }

    # 输出报告
    switch ($OutputFormat) {
        "json"  { Show-ReportJson }
        "brief" { Show-ReportBrief }
        default { Show-ReportText }
    }

    # 退出码
    if ($WarnOnly) {
        exit 0
    }

    switch ($Script:OverallStatus) {
        "healthy"  { exit 0 }
        "warning"  { exit 1 }
        "critical" { exit 2 }
        default    { exit 0 }
    }
}

Main
