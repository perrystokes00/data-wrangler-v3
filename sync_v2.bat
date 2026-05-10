@echo off
setlocal enabledelayedexpansion
echo.
echo ========================================
echo  Data Wrangler v2 - Sync to Dist
echo ========================================
echo.

:: ── Paths ────────────────────────────────────────────────────────────────────
set SRC=C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v2
set DST=C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v2_dist
set ISS=C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v2\DataWrangler_v2.iss
set INNO=C:\Program Files (x86)\Inno Setup 6\ISCC.exe

:: ── Verify folders exist ──────────────────────────────────────────────────────
if not exist "%SRC%" (
    echo ERROR: Source folder not found: %SRC%
    pause & exit /b 1
)
if not exist "%DST%" (
    echo ERROR: Dist folder not found: %DST%
    echo Run build_dist_v2.bat first to create it.
    pause & exit /b 1
)

echo Source : %SRC%
echo Dest   : %DST%
echo.

:: ── Root Python files ────────────────────────────────────────────────────────
echo [1/8] Syncing root Python files...
for %%F in (
    app.py
    page_pipeline.py
    page_bulk.py
    page_db_explorer.py
    page_data_model.py
    page_rules.py
    page_seed.py
    page_splash.py
    page_std_catalog.py
    page_file_inventory_gov.py
    page_file_workbench.py
    setup_database.py
    page_ppdm_map.py
    page_licence.py
    page_shapefile_catalog.py
    bulk_runner.py
    seed_queue.py
    ui_helpers.py
    ppdm_viewer.html
    run.bat
    install.bat
    requirements.txt
    README.md
    EULA.txt
) do (
    if exist "%SRC%\%%F" (
        copy /y "%SRC%\%%F" "%DST%\%%F" >nul
        echo        Copied: %%F
    ) else (
        echo        MISSING: %%F
    )
)

:: ── .env ─────────────────────────────────────────────────────────────────────
echo.
echo [2/8] Syncing .env...
if exist "%SRC%\.env" (
    copy /y "%SRC%\.env" "%DST%\.env" >nul
    echo        Copied: .env
) else (
    echo        MISSING: .env
)

:: ── .streamlit ───────────────────────────────────────────────────────────────
echo.
echo [3/8] Syncing .streamlit...
if not exist "%DST%\.streamlit" mkdir "%DST%\.streamlit"
if exist "%SRC%\.streamlit\config.toml" (
    copy /y "%SRC%\.streamlit\config.toml" "%DST%\.streamlit\config.toml" >nul
    echo        Copied: .streamlit\config.toml
) else (
    echo        MISSING: .streamlit\config.toml
)

:: ── modules (explicit list — excludes debug/dev files) ───────────────────────
echo.
echo [4/8] Syncing modules\...
if not exist "%DST%\modules" mkdir "%DST%\modules"
for %%F in (
    __init__.py
    app_config.json
    db.py
    db_dialect.py
    db_pool.py
    delete_util.py
    dlis_catalog.py
    fk.py
    fk_catalog.py
    fk_entity.py
    import_hashlib.py
    las_catalog.py
    las_loader.py
    licence.py
    mapping.py
    normalize.py
    p190_catalog.py
    ppdm_agent.py
    promote.py
    schema.py
    seed_catalog.py
    segy_catalog.py
    staging.py
    user_rules.json
    user_rules.py
    validate.py
    wl_file_map.py
    file_inventory.py
    file_inventory_governance.py
    file_header_catalog.py
    inv_auth.py
    inv_email.py
    inv_workbench.py
    audit_log.py
    catalog_dialect.py
    file_header_store.py
    seis_filename_parser.py
    shapefile_catalog.py
) do (
    if exist "%SRC%\modules\%%F" (
        copy /y "%SRC%\modules\%%F" "%DST%\modules\%%F" >nul
        echo        Copied: modules\%%F
    ) else (
        echo        MISSING: modules\%%F
    )
)

:: ── schema_registry ──────────────────────────────────────────────────────────
echo.
echo [5/8] Syncing schema_registry\...
if not exist "%DST%\schema_registry" mkdir "%DST%\schema_registry"
robocopy "%SRC%\schema_registry" "%DST%\schema_registry" /MIR /NFL /NDL /NJH /NJS /NC /NS /NP >nul
echo        Done.

:: ── seed_catalog ─────────────────────────────────────────────────────────────
echo.
echo [6/8] Syncing seed_catalog\...
if not exist "%DST%\seed_catalog" mkdir "%DST%\seed_catalog"
robocopy "%SRC%\seed_catalog" "%DST%\seed_catalog" *.csv /MIR /NFL /NDL /NJH /NJS /NC /NS /NP >nul
echo        Done.

:: ── assets ───────────────────────────────────────────────────────────────────
echo.
echo [7/8] Syncing assets\...
if not exist "%DST%\assets" mkdir "%DST%\assets"
robocopy "%SRC%\assets" "%DST%\assets" /MIR /NFL /NDL /NJH /NJS /NC /NS /NP >nul
echo        Done.

:: ── Cleanup dist — remove dev/debug files ────────────────────────────────────
echo.
echo [8/8] Cleaning up dist...

:: Debug and dev files that must not ship
for %%F in (
    modules\bad_rows_strat_well_section_stg_s.xlsx
    modules\mapping_cache.json
    modules\normalize_timing.txt
    modules\promote_debug.txt
    modules\licence.json
    modules\__pycache__
    __pycache__
    docs
    licence.json
    bulk_history.json
    bulk_queue.json
    bulk_runner.log
    bulk_fk_seed.log
    bulk_watcher.json
    las_catalog.db
    seis_catalog.db
    sf_connect_debug.log
) do (
    if exist "%DST%\%%F" (
        :: Check if it's a directory or file
        if exist "%DST%\%%F\" (
            rd /s /q "%DST%\%%F"
        ) else (
            del /f /q "%DST%\%%F"
        )
        echo        Removed: %%F
    )
)
echo        Done.

:: ── Summary ──────────────────────────────────────────────────────────────────
echo.
echo ========================================
echo  Sync complete!
echo ========================================
echo.

:: ── Offer to compile with Inno ───────────────────────────────────────────────
if not exist "%INNO%" (
    echo Inno Setup not found at: %INNO%
    echo Skipping compile step.
    echo.
    pause & exit /b 0
)

set /p COMPILE="Compile installer now? (Y/N): "
if /i "%COMPILE%"=="Y" (
    echo.
    echo Compiling installer...
    "%INNO%" "%ISS%"
    if errorlevel 1 (
        echo ERROR: Inno Setup compile failed.
        pause & exit /b 1
    )
    echo.
    echo ========================================
    echo  DataWrangler_Setup.exe is ready!
    echo ========================================
    echo.
)

pause
