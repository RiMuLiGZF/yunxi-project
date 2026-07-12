@echo off
chcp 65001 >nul
title 云汐系统 - 启动中...

echo ============================================================
echo    云汐系统 Yunxi System
echo    正在启动，请稍候...
echo ============================================================
echo.

REM 进入项目目录
cd /d "%~dp0.."

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.9+
    pause
    exit /b 1
)

echo [1/6] 启动 M8 管理工作台 (端口 8000)...
start "Yunxi-M8" /B python -m uvicorn M8-control-tower.backend.main:app --host 0.0.0.0 --port 8000
timeout /t 3 /nobreak >nul

echo [2/6] 启动 M1 多Agent调度中心 (端口 8001)...
cd M1-agent-cluster
start "Yunxi-M1" /B python server.py
cd ..
timeout /t 2 /nobreak >nul

echo [3/6] 启动 M2 技能集群 (端口 8002)...
cd M2-skills-cluster
start "Yunxi-M2" /B python start_server.py
cd ..
timeout /t 2 /nobreak >nul

echo [4/6] 启动 M3 端云协同内核 (端口 8003)...
cd M3-edge-cloud
start "Yunxi-M3" /B python server.py
cd ..
timeout /t 2 /nobreak >nul

echo [5/6] 启动 M5 潮汐记忆系统 (端口 8005)...
cd M5-tide-memory
start "Yunxi-M5" /B python server.py
cd ..
timeout /t 2 /nobreak >nul

echo [6/6] 等待所有服务就绪...
timeout /t 5 /nobreak >nul

echo.
echo ============================================================
echo    云汐系统启动完成！
echo ============================================================
echo.
echo  访问地址:
echo    统一门户:  http://localhost:8000/
echo    启动页:    http://localhost:8000/startup/
echo    M8管理台:  http://localhost:8000/m8/login.html
echo    汐舷监控:  http://localhost:8000/xian/main-running.html
echo    积木平台:  http://localhost:8000/m7/workflow-list.html
echo.
echo  登录账号: admin / admin123456
echo.
echo  提示: 关闭此窗口不会停止服务
echo        如需停止，请运行 stop.bat
echo ============================================================
echo.

REM 自动打开浏览器
start "" "http://localhost:8000/startup/"

pause
