@echo off
rem ============================================================
rem  Force-stop all Google Antigravity IDE and agy.exe CLI/hub processes.
rem  Usage:  kill_antigravity.bat            (kill once and verify)
rem          kill_antigravity.bat -ListOnly  (just list, kill nothing)
rem          kill_antigravity.bat -DryRun    (show targets, kill nothing)
rem          kill_antigravity.bat -Watch     (keep sweeping until Ctrl+C)
rem ============================================================
setlocal
chcp 65001 >nul

if not exist "%~dp0kill_antigravity.ps1" (
    echo [error] kill_antigravity.ps1 not found next to this batch file.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill_antigravity.ps1" %*

set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo [done] No Antigravity process is running.
) else (
    echo [warn] Antigravity processes remain, or the sweep was refused because this
    echo        console is running inside Antigravity. See the message above.
)
if "%~1"=="" pause
exit /b %RC%
