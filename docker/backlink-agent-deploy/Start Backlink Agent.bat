@echo off
title Backlink Agent - Desktop Start
set "DEPLOY=C:\Users\TheOne\Downloads\backlink-agent-deploy\backlink-agent-deploy"
echo.
echo === Backlink Agent (desktop launcher) ===
echo Deploy folder: %DEPLOY%
echo.
echo TIP: Start News Agent first (Bifrost on port 8888).
echo.
if not exist "%DEPLOY%\start.ps1" (
    echo ERROR: start.ps1 not found in deploy folder.
    echo Copy deploy files into:
    echo   %DEPLOY%
    echo.
    pause
    exit /b 1
)
cd /d "%DEPLOY%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEPLOY%\start.ps1"
if errorlevel 1 (
    echo.
    echo FAILED - read the error above, then press any key to close.
    pause
    exit /b 1
)
echo.
echo OK - Backlink Agent is running.
timeout /t 15
