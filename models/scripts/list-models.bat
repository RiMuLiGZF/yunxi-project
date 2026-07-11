@echo off
chcp 65001 >nul
REM ============================================================
REM 云汐系统 - 列出已安装的 Ollama 模型
REM ============================================================

echo ========================================
echo    云汐系统 - 已安装模型列表
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

"%OLLAMA_PATH%" list

echo.
echo ========================================
echo 常用操作:
echo   拉取模型: pull-model.bat [模型名]
echo   启动服务: start-ollama.bat
echo ========================================
echo.
pause
