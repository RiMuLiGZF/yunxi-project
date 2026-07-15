#Requires -Version 5.1
<#
.SYNOPSIS
    云汐桌面启动器 - 安装脚本

.DESCRIPTION
    检查 Python 环境、安装依赖、创建桌面快捷方式，并可选择注册开机启动。

.PARAMETER SkipStartup
    跳过注册开机启动项。

.EXAMPLE
    .\install.ps1
    .\install.ps1 -SkipStartup
#>
[CmdletBinding()]
param(
    [switch]$SkipStartup
)

$ErrorActionPreference = "Stop"

# ============ 路径配置 ============
$LauncherDir = "c:\云汐\工作台\yunxi-project\tools\desktop-launcher"
$TrayScript = Join-Path $LauncherDir "yunxi-tray.py"
$PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
$PipExe = (Get-Command pip -ErrorAction SilentlyContinue).Source

# ============ 颜色输出辅助 ============
function Write-ColorLine {
    param([string]$Text, [string]$Color = "White")
    $colors = @{ "Red" = "Red"; "Green" = "Green"; "Yellow" = "Yellow"; "Cyan" = "Cyan" }
    Write-Host $Text -ForegroundColor $colors[$Color]
}

Write-ColorLine "========================================" "Cyan"
Write-ColorLine "   云汐桌面启动器 - 安装向导" "Cyan"
Write-ColorLine "========================================" "Cyan"
Write-Host ""

# ============ 1. 检查 Python ============
Write-ColorLine "[1/5] 检查 Python 环境..." "Cyan"
if (-not $PythonExe) {
    Write-ColorLine "错误: 未检测到 Python。请先安装 Python 3.10+ 并添加到 PATH。" "Red"
    Write-ColorLine "下载地址: https://www.python.org/downloads/" "Yellow"
    exit 1
}

$pyVersion = & python --version 2>&1
Write-ColorLine "  检测到: $pyVersion ($PythonExe)" "Green"

# 检查版本号 >= 3.10
$verMatch = [regex]::Match($pyVersion, '(\d+)\.(\d+)')
if ($verMatch.Success) {
    $major = [int]$verMatch.Groups[1].Value
    $minor = [int]$verMatch.Groups[2].Value
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
        Write-ColorLine "警告: Python 版本过低，建议升级到 3.10+。" "Yellow"
    }
}

# ============ 2. 检查 pip ============
Write-ColorLine "[2/5] 检查 pip..." "Cyan"
if (-not $PipExe) {
    Write-ColorLine "错误: 未检测到 pip。请确保 Python 安装时包含了 pip。" "Red"
    exit 1
}
$pipVersion = & pip --version 2>&1
Write-ColorLine "  检测到: $pipVersion" "Green"

# ============ 3. 安装依赖 ============
Write-ColorLine "[3/5] 安装 Python 依赖..." "Cyan"
$deps = @("pystray", "pillow", "psutil", "httpx")
foreach ($dep in $deps) {
    Write-Host "  安装 $dep ... " -NoNewline
    try {
        & pip install $dep --quiet 2>$null
        Write-ColorLine "OK" "Green"
    } catch {
        Write-ColorLine "失败 ($_)" "Red"
    }
}

# 尝试安装可选依赖 keyboard
Write-Host "  安装 keyboard (可选，全局快捷键) ... " -NoNewline
try {
    & pip install keyboard --quiet 2>$null
    Write-ColorLine "OK" "Green"
} catch {
    Write-ColorLine "跳过" "Yellow"
}

# ============ 4. 创建桌面快捷方式 ============
Write-ColorLine "[4/5] 创建桌面快捷方式..." "Cyan"
$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "云汐桌面启动器.lnk"

$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PythonExe
$Shortcut.Arguments = '"' + $TrayScript + '"'
$Shortcut.WorkingDirectory = $LauncherDir
$Shortcut.Description = "云汐系统桌面启动器 - 一键启停与状态监控"
$Shortcut.WindowStyle = 7  # 7 = Minimized (后台运行)

# 尝试设置图标（如果存在自定义图标文件，否则用 python.exe 的图标）
$iconPath = Join-Path $LauncherDir "assets\icon-ready.png"
if (Test-Path $iconPath) {
    $Shortcut.IconLocation = $iconPath
} else {
    $Shortcut.IconLocation = "$PythonExe,0"
}

$Shortcut.Save()
Write-ColorLine "  已创建: $ShortcutPath" "Green"

# ============ 5. 注册开机启动（可选） ============
if (-not $SkipStartup) {
    Write-ColorLine "[5/5] 注册开机启动..." "Cyan"
    $StartupDir = [Environment]::GetFolderPath("Startup")
    $StartupShortcut = Join-Path $StartupDir "云汐桌面启动器.lnk"

    $StartupSC = $WshShell.CreateShortcut($StartupShortcut)
    $StartupSC.TargetPath = $PythonExe
    $StartupSC.Arguments = '"' + $TrayScript + '"'
    $StartupSC.WorkingDirectory = $LauncherDir
    $StartupSC.Description = "云汐系统开机自启"
    $StartupSC.WindowStyle = 7
    $StartupSC.IconLocation = "$PythonExe,0"
    $StartupSC.Save()

    Write-ColorLine "  已创建开机启动项: $StartupShortcut" "Green"
} else {
    Write-ColorLine "[5/5] 已跳过开机启动注册（-SkipStartup）" "Yellow"
}

Write-Host ""
Write-ColorLine "========================================" "Green"
Write-ColorLine "   安装完成！" "Green"
Write-ColorLine "========================================" "Green"
Write-Host ""
Write-Host "  使用方式:"
Write-Host "    1. 双击桌面快捷方式 '云汐桌面启动器' 启动托盘图标"
Write-Host "    2. 右键托盘图标查看菜单: 启动/停止系统、查看模块状态"
Write-Host "    3. 左键双击托盘图标打开统一门户"
Write-Host ""
Write-Host "  依赖已安装: pystray, pillow, psutil, httpx"
if (-not $SkipStartup) {
    Write-Host "  开机启动: 已启用（下次登录自动启动）"
}
Write-Host ""

# 询问是否立即启动
$choice = Read-Host "是否立即启动云汐桌面启动器? [Y/n]"
if ($choice -eq "" -or $choice -match "^[Yy]$") {
    Write-ColorLine "正在启动..." "Cyan"
    Start-Process -FilePath $PythonExe -ArgumentList '"' + $TrayScript + '"' -WorkingDirectory $LauncherDir
}
