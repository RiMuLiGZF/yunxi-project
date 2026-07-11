# ============================================================
# 云汐系统 - Ollama 一键配置脚本
# 功能：检查 Ollama 安装、启动服务、拉取默认模型
# 运行方式: PowerShell -ExecutionPolicy Bypass -File setup-ollama.ps1
# ============================================================

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   云汐系统 - Ollama 一键配置" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 检查 Ollama 安装
$ollamaPath = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"

Write-Host "[1/4] 检查 Ollama 安装..." -ForegroundColor Yellow
if (-not (Test-Path $ollamaPath)) {
    Write-Host "  [错误] 未找到 Ollama 安装" -ForegroundColor Red
    Write-Host "  请从 https://ollama.com/ 下载安装" -ForegroundColor Red
    Read-Host "按回车键退出"
    exit 1
}
$version = & $ollamaPath --version 2>&1
Write-Host "  [OK] Ollama 已安装: $version" -ForegroundColor Green

# 2. 检查 Ollama 服务状态
Write-Host ""
Write-Host "[2/4] 检查 Ollama 服务状态..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 3 -UseBasicParsing
    Write-Host "  [OK] Ollama 服务正在运行" -ForegroundColor Green
    $serviceRunning = $true
} catch {
    Write-Host "  [提示] Ollama 服务未运行，正在启动..." -ForegroundColor Yellow
    # 启动 Ollama 服务（后台运行）
    Start-Process $ollamaPath -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 5
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 10 -UseBasicParsing
        Write-Host "  [OK] Ollama 服务已启动" -ForegroundColor Green
        $serviceRunning = $true
    } catch {
        Write-Host "  [错误] Ollama 服务启动失败" -ForegroundColor Red
        Write-Host "  请手动运行: $ollamaPath serve" -ForegroundColor Red
        Read-Host "按回车键退出"
        exit 1
    }
}

# 3. 拉取默认模型
Write-Host ""
Write-Host "[3/4] 拉取默认模型 qwen2.5:7b..." -ForegroundColor Yellow

# 先检查是否已安装
$models = & $ollamaPath list 2>&1
$qwenInstalled = $models | Select-String -Pattern "qwen2\.5:7b"

if ($qwenInstalled) {
    Write-Host "  [OK] qwen2.5:7b 已安装" -ForegroundColor Green
} else {
    Write-Host "  [提示] 开始拉取 qwen2.5:7b (约 4.7GB)..." -ForegroundColor Yellow
    Write-Host "  [提示] 下载时间取决于网络速度，请耐心等待" -ForegroundColor Yellow
    Write-Host ""
    
    & $ollamaPath pull qwen2.5:7b
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "  [OK] qwen2.5:7b 拉取成功！" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "  [错误] 模型拉取失败" -ForegroundColor Red
        Read-Host "按回车键退出"
        exit 1
    }
}

# 4. 验证模型可用性
Write-Host ""
Write-Host "[4/4] 验证模型可用性..." -ForegroundColor Yellow
try {
    $body = @{
        model = "qwen2.5:7b"
        prompt = "你好，请用一句话介绍你自己"
        stream = $false
    } | ConvertTo-Json
    
    $response = Invoke-WebRequest -Uri "http://localhost:11434/api/generate" -Method Post -Body $body -ContentType "application/json" -TimeoutSec 60 -UseBasicParsing
    $result = $response.Content | ConvertFrom-Json
    
    Write-Host "  [OK] 模型响应正常" -ForegroundColor Green
    Write-Host "  模型回复: $($result.response.Substring(0, [Math]::Min(50, $result.response.Length)))..." -ForegroundColor Gray
} catch {
    Write-Host "  [警告] 模型测试失败，但模型可能仍可用" -ForegroundColor Yellow
    Write-Host "  错误: $($_.Exception.Message)" -ForegroundColor Gray
}

# 完成
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   Ollama 配置完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "模型管理脚本位于: models\scripts\"
Write-Host "  - start-ollama.bat    启动服务"
Write-Host "  - pull-model.bat      拉取模型"
Write-Host "  - list-models.bat     查看列表"
Write-Host ""
Write-Host "切换到本地模型请修改 config\yunxi.env:"
Write-Host "  LLM_PROVIDER=ollama"
Write-Host "  OLLAMA_MODEL=qwen2.5:7b"
Write-Host ""

Read-Host "按回车键退出"
