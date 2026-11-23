@echo off
rem ============================================================
rem  Force-stop Claude Code CLI and Claude desktop processes.
rem  Usage:  kill_claude.bat            (kill once and verify)
rem          kill_claude.bat -ListOnly  (just list, kill nothing)
rem          kill_claude.bat -DryRun    (show targets, kill nothing)
rem          kill_claude.bat -Watch     (keep sweeping until Ctrl+C)
rem ============================================================
setlocal
chcp 65001 >nul

if not exist "%~dp0kill_claude.ps1" (
    echo [error] kill_claude.ps1 not found next to this batch file.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill_claude.ps1" %*

set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo [done] Claude process command completed successfully.
) else (
    echo [warn] Some processes survived - a VS Code extension or supervisor may have restarted Claude Code.
    echo        Close the Claude Code panel and retry, or run: kill_claude.bat -Watch
)
if "%~1"=="" pause
exit /b %RC%
