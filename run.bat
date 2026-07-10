@echo off
echo.
echo ========================================
echo  Data Wrangler
echo ========================================
echo.

set APPDIR=%~dp0
set STREAMLIT=%LOCALAPPDATA%\DataWrangler\venv\Scripts\streamlit.exe

:: Check venv exists
if not exist "%STREAMLIT%" (
    echo ERROR: Data Wrangler is not fully installed.
    echo        Please run install.bat first.
    echo.
    pause
    exit /b 1
)

echo Starting Data Wrangler...
echo Opening in your browser at http://localhost:8501
echo.
echo Press Ctrl+C to stop.
echo.
"%STREAMLIT%" run "%APPDIR%app.py"
pause
