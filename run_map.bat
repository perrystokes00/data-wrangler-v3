@echo off
:: DataView Map Window Launcher
:: Opens the standalone map app on port 8503
:: Drag browser window to second monitor for dual-screen workflow

cd /d "%~dp0"

:: Activate venv
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo WARNING: venv not found, using system Python
)

echo.
echo ============================================
echo  DataView Map Window
echo  http://localhost:8503
echo ============================================
echo.
echo Open the URL above in a browser window,
echo then drag it to your second monitor.
echo.
echo Press Ctrl+C to stop the map server.
echo.

streamlit run map_app.py ^
    --server.port 8503 ^
    --server.headless true ^
    --browser.gatherUsageStats false

pause
