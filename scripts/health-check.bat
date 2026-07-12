@echo off
REM ============================================================
REM 云汐系统 - 健康检查脚本
REM ============================================================

setlocal enabledelayedexpansion

echo ============================================================
echo    云汐系统 - 模块健康检查
echo ============================================================
echo.

set MODULES="M1=8001" "M2=8002" "M3=8003" "M4=8004" "M5=8005" "M6=8000" "M7=3001" "M8=8080"

for %%m in (%MODULES%) do (
    for /f "tokens=1,2 delims==" %%a in ("%%~m") do (
        set MODULE=%%a
        set PORT=%%b
        set STATUS=DOWN

        ping -n 1 127.0.0.1 >nul 2>&1

        REM 使用 curl 检查
        curl -s -o nul -w "%%{http_code}" http://localhost:!PORT!/health > temp_status.txt 2>nul
        set /p HTTP_CODE=<temp_status.txt
        del temp_status.txt

        if "!HTTP_CODE!"=="200" (
            set STATUS=运行中
            echo [OK]   !MODULE! (端口 !PORT!) - !STATUS!
        ) else (
            echo [DOWN] !MODULE! (端口 !PORT!) - 未运行
        )
    )
)

echo.
echo ============================================================
pause
