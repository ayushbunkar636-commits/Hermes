@echo off
title Backlink Agent Start
cd /d "%~dp0"
echo.
echo === Backlink Agent ===
echo Folder: %CD%
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 (
    echo.
    echo FAILED - read the error above, then press any key to close.
    pause >nul
    exit /b 1
)
echo.
echo OK - window closes in 15 seconds, or press any key now.
pause >nul
