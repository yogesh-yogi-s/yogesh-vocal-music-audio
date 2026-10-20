@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
    py -3.13 "scripts\start_local.py"
) else (
    python "scripts\start_local.py"
)

if errorlevel 1 (
    echo.
    echo VMA could not start. Read the message above, then press any key to close.
    pause >nul
)
