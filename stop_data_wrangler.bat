@echo off
title Stop Data Wrangler
echo Stopping Data Wrangler...

:: Kill streamlit process
taskkill /f /im streamlit.exe >nul 2>&1
if %errorlevel% == 0 (
    echo Data Wrangler stopped successfully.
) else (
    :: Try killing by window title
    taskkill /f /fi "WINDOWTITLE eq Data Wrangler*" >nul 2>&1
    if %errorlevel% == 0 (
        echo Data Wrangler stopped successfully.
    ) else (
        echo Data Wrangler was not running or could not be stopped.
    )
)

timeout /t 2 >nul
