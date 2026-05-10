@echo off
setlocal enabledelayedexpansion
echo.
echo ========================================
echo  Data Wrangler v2 - Installation
echo ========================================
echo.

set APPDIR=%~dp0
set PYDIR=%LOCALAPPDATA%\DataWrangler\python
set VENV=%LOCALAPPDATA%\DataWrangler\venv
set PYTHON=%PYDIR%\python.exe
set PIP=%PYDIR%\Scripts\pip.exe
set VENVPIP=%VENV%\Scripts\pip.exe
set VENVPY=%VENV%\Scripts\python.exe

:: ── Step 1: Extract Python 3.12 ──────────────────────────────────────────────
echo [1/5] Setting up Python 3.12...

if exist "%PYDIR%\Scripts\virtualenv.exe" (
    echo        Python 3.12 already installed. Skipping.
    goto PYTHONREADY
)

if exist "%PYDIR%" (
    echo        Cleaning up previous install...
    rd /s /q "%PYDIR%" >nul 2>&1
)
if exist "%VENV%" (
    rd /s /q "%VENV%" >nul 2>&1
)

echo        Extracting Python 3.12 - please wait...
mkdir "%PYDIR%"

set EXTRACTED=0
tar -xf "%APPDIR%python-3.12.10-embed-amd64.zip" -C "%PYDIR%" >nul 2>&1
if not errorlevel 1 set EXTRACTED=1

if "%EXTRACTED%"=="0" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path '%APPDIR%python-3.12.10-embed-amd64.zip' -DestinationPath '%PYDIR%' -Force" >nul 2>&1
    if not errorlevel 1 set EXTRACTED=1
)

if "%EXTRACTED%"=="0" (
    pwsh -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path '%APPDIR%python-3.12.10-embed-amd64.zip' -DestinationPath '%PYDIR%' -Force" >nul 2>&1
    if not errorlevel 1 set EXTRACTED=1
)

if "%EXTRACTED%"=="0" (
    cscript //nologo "%APPDIR%extract.vbs" "%APPDIR%python-3.12.10-embed-amd64.zip" "%PYDIR%" >nul 2>&1
    if not errorlevel 1 set EXTRACTED=1
)

if "%EXTRACTED%"=="0" (
    echo.
    echo ERROR: Could not extract Python. All extraction methods failed.
    echo        Please contact support@datawranglersolutions.com
    pause
    exit /b 1
)

"%PYTHON%" -c "import pathlib; p=pathlib.Path(r'%PYDIR%\python312._pth'); p.write_text(p.read_text().replace('#import site','import site'))"

if not exist "%PYTHON%" (
    echo.
    echo ERROR: Python extraction failed.
    echo        Expected: %PYTHON%
    pause
    exit /b 1
)
echo        Python 3.12 ready.

echo        Installing pip...
"%PYTHON%" "%APPDIR%get-pip.py" --quiet --no-warn-script-location
if errorlevel 1 (
    echo ERROR: pip installation failed.
    pause & exit /b 1
)

echo        Installing virtualenv...
"%PIP%" install virtualenv --quiet --no-warn-script-location
if errorlevel 1 (
    echo ERROR: virtualenv installation failed.
    pause & exit /b 1
)
echo        pip and virtualenv ready.

:PYTHONREADY

:: ── Step 2: Create virtual environment ──────────────────────────────────────
echo.
echo [2/5] Setting up virtual environment...
if exist "%VENVPY%" (
    echo        Virtual environment already exists. Skipping.
) else (
    "%PYTHON%" -m virtualenv "%VENV%" --quiet
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause & exit /b 1
    )
    echo        Virtual environment created.
)

:: ── Step 3: Upgrade pip ──────────────────────────────────────────────────────
echo.
echo [3/5] Upgrading pip...
"%VENVPY%" -m pip install --upgrade pip --quiet >nul 2>&1
echo        Done.

:: ── Step 4: Install dependencies ────────────────────────────────────────────
echo.
echo [4/5] Installing dependencies...
echo.

set PACKAGES=streamlit==1.45.0 pandas==2.2.3 SQLAlchemy==2.0.43 numpy==2.0.1 pyodbc==5.3.0 oracledb==3.4.2 snowflake-sqlalchemy==1.9.0 snowflake-connector-python==4.4.0 python-dotenv==1.2.1 openpyxl==3.1.5 lasio==0.31 requests==2.32.5 folium==0.20.0 segyio==1.9.14 dlisio==1.0.4 matplotlib==3.9.2 plotly==5.24.1
set /a TOTAL=17
set /a COUNT=0

for %%P in (%PACKAGES%) do (
    set /a COUNT+=1
    set /a PCT=!COUNT!*100/!TOTAL!
    set "BAR="
    set /a FILLED=!PCT!/5
    for /l %%i in (1,1,!FILLED!) do set "BAR=!BAR!#"
    for /l %%i in (!FILLED!,1,19) do set "BAR=!BAR!-"
    <nul set /p "=        [!BAR!] !PCT!%% - Installing %%P...    "
    "%VENVPIP%" install %%P --quiet >nul 2>&1
    echo.
)

:: ── Step 5: Done ─────────────────────────────────────────────────────────────
echo.
echo [5/5] Finalizing...
echo        All dependencies installed successfully.
echo.
echo ========================================
echo  Installation complete!
echo  Run Data Wrangler from your desktop
echo  or Start Menu shortcut.
echo ========================================
echo.
pause
