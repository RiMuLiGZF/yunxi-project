@echo off
chcp 65001 >nul
REM ============================================================
REM 云汐系统 - 拉取 Ollama 模型
REM 用法: pull-model.bat [模型名]
REM 示例: pull-model.bat qwen2.5:7b
REM ============================================================

setlocal enabledelayedexpansion

echo ========================================
echo    云汐系统 - 拉取 Ollama 模型
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

REM 获取模型名参数，默认 qwen2.5:7b
set MODEL=%~1
if "%MODEL%"=="" set MODEL=qwen2.5:7b

echo [信息] 正在拉取模型: %MODEL%
echo [信息] 这可能需要几分钟时间，请耐心等待...
echo.

"%OLLAMA_PATH%" pull %MODEL%

if %errorlevel% equ 0 (
    echo.
    echo [成功] 模型 %MODEL% 拉取完成！
    echo [提示] 可运行 list-models.bat 查看已安装模型
) else (
    echo.
    echo [失败] 模型拉取失败，请检查网络连接
)

echo.
pause
