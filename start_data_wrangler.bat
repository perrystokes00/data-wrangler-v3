@echo off
title Data Wrangler
echo ============================================
echo  Data Wrangler v2
echo ============================================
echo.

cd /d "%~dp0"

:: Activate venv if it exists
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

:: Show which python and streamlit are being used
echo Python:
python --version
echo Streamlit:
python -m streamlit --version

echo.
echo Starting...
echo.

python -m streamlit run app.py --server.port 8501 --server.headless false --browser.gatherUsageStats false

echo.
echo Server stopped.
pause
