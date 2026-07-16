@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-workbench.ps1"
set EXITCODE=%ERRORLEVEL%
if %EXITCODE% neq 0 (
    echo.
    echo Workbench startup failed (exit code: %EXITCODE%).
    echo Check logs\runtime for details.
    pause
)
endlocal
