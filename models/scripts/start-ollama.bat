@echo off
chcp 65001 >nul
REM ============================================================
REM 云汐系统 - 启动 Ollama 服务
REM ============================================================

echo ========================================
echo    云汐系统 - 启动 Ollama 服务
echo ========================================
echo.

REM Ollama 默认安装路径
set OLLAMA_PATH=C:\Users\XiZho\AppData\Local\Programs\Ollama\ollama.exe

if not exist "%OLLAMA_PATH%" (
    echo [错误] 未找到 Ollama，路径: %OLLAMA_PATH%
    echo 请先安装 Ollama: https://ollama.com/
    pause
    exit /b 1
)

echo [信息] 正在启动 Ollama 服务...
echo [信息] 服务地址: http://localhost:11434
echo [提示] 关闭此窗口将停止服务
echo.

"%OLLAMA_PATH%" serve

pause
