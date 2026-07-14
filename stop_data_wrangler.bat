@echo off
setlocal enabledelayedexpansion
title Stop DataView

:: ── set this to match the --server.port in start_data_wrangler.bat ──
set "PORT=8502"

echo Stopping DataView (port %PORT%) ...

set "FOUND="
:: find the PID listening on the app port and kill its whole tree (server + child runner)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr LISTENING') do (
    set "FOUND=1"
    echo   killing PID %%a
    taskkill /f /t /pid %%a >nul 2>&1
)

if not defined FOUND (
    echo   nothing listening on %PORT% - trying window title fallback ...
    taskkill /f /fi "WINDOWTITLE eq DataView*" >nul 2>&1
    if !errorlevel! == 0 (
        echo   stopped via window title.
    ) else (
        echo   DataView was not running.
    )
) else (
    echo   DataView stopped.
)

timeout /t 2 >nul
endlocal
