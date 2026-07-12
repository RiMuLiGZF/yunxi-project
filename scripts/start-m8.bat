@echo off
REM ============================================================
REM 云汐系统 - 一键启动脚本 (Windows)
REM 启动 M8 管理工作台后端
REM ============================================================

setlocal enabledelayedexpansion

echo ============================================================
echo    云汐系统 M8 管理工作台 - 启动脚本
echo ============================================================
echo.

REM 切换到脚本所在目录
cd /d "%~dp0"
cd ..\..

set PROJECT_ROOT=%cd%
echo 项目根目录: %PROJECT_ROOT%
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

REM 检查虚拟环境
if not exist "venv\Scripts\python.exe" (
    echo [INFO] 正在创建虚拟环境...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] 创建虚拟环境失败
        pause
        exit /b 1
    )
)

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 安装依赖
echo [INFO] 检查/安装依赖...
pip install -r M8-control-tower\backend\requirements.txt -q
if errorlevel 1 (
    echo [WARNING] 部分依赖安装可能失败，尝试继续...
)

REM 设置 Python path
set PYTHONPATH=%PROJECT_ROOT%;%PYTHONPATH%

echo.
echo [INFO] 启动 M8 管理工作台后端...
echo [INFO] 访问地址: http://localhost:8080
echo [INFO] API 文档: http://localhost:8080/docs
echo [INFO] 默认账号: admin / admin123456
echo.
echo [提示] 按 Ctrl+C 停止服务
echo ============================================================

cd M8-control-tower\backend
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload

pause
