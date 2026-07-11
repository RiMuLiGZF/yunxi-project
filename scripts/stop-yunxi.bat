@echo off
chcp 65001 >nul
title 云汐系统 - 停止服务

echo ============================================================
echo    云汐系统 - 停止所有服务
echo ============================================================
echo.

echo 正在查找云汐相关进程...
echo.

REM 查找并列出所有云汐相关Python进程
tasklist /fi "imagename eq python.exe" /v 2>nul | findstr /i "yunxi uvicorn server"

echo.
echo 正在停止所有云汐服务进程...
echo.

REM 停止所有相关Python进程（端口8000-8005 + 3001）
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do (
    echo 停止 M8 (端口8000, PID: %%a)
    taskkill /pid %%a /f /t >nul 2>&1
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001 " ^| findstr LISTENING') do (
    echo 停止 M1 (端口8001, PID: %%a)
    taskkill /pid %%a /f /t >nul 2>&1
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8002 " ^| findstr LISTENING') do (
    echo 停止 M2 (端口8002, PID: %%a)
    taskkill /pid %%a /f /t >nul 2>&1
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8003 " ^| findstr LISTENING') do (
    echo 停止 M3 (端口8003, PID: %%a)
    taskkill /pid %%a /f /t >nul 2>&1
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8005 " ^| findstr LISTENING') do (
    echo 停止 M5 (端口8005, PID: %%a)
    taskkill /pid %%a /f /t >nul 2>&1
)

echo.
echo ============================================================
echo    所有云汐服务已停止
echo ============================================================
echo.
pause
