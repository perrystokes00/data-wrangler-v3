@echo off
setlocal

set SRC=C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v2
set DEST=C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v2_dist

echo.
echo Building clean distribution folder...
echo Source : %SRC%
echo Dest   : %DEST%
echo.

:: Remove and recreate dest
if exist "%DEST%" (
    echo Removing existing dist folder...
    rmdir /s /q "%DEST%"
)
mkdir "%DEST%"

:: ── Root app files ──────────────────────────────────────────────────────────
echo Copying root app files...
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
    page_ppdm_map.py
    page_licence.py
    bulk_runner.py
    seed_queue.py
    ui_helpers.py
    run.bat
    install.bat
    requirements.txt
    README.md
    EULA.txt
) do (
    if exist "%SRC%\%%F" (
        copy /y "%SRC%\%%F" "%DEST%\%%F" >nul
        echo        Copied: %%F
    ) else (
        echo   MISSING: %%F  ^^^<^^^<^^^< CHECK THIS
    )
)

:: ── .streamlit ──────────────────────────────────────────────────────────────
echo.
echo Copying .streamlit config...
mkdir "%DEST%\.streamlit"
copy /y "%SRC%\.streamlit\config.toml" "%DEST%\.streamlit\config.toml" >nul

:: ── modules ─────────────────────────────────────────────────────────────────
echo.
echo Copying modules...
mkdir "%DEST%\modules"
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
) do (
    if exist "%SRC%\modules\%%F" (
        copy /y "%SRC%\modules\%%F" "%DEST%\modules\%%F" >nul
    ) else (
        echo   MISSING: modules\%%F  ^^^<^^^<^^^< CHECK THIS
    )
)

:: ── schema_registry ─────────────────────────────────────────────────────────
echo.
echo Copying schema registry...
mkdir "%DEST%\schema_registry"
for %%F in (
    ppdm_39_fk_catalog.json
    ppdm_39_fk_catalog_sqlserver.json
    ppdm_39_fk_catalog_oracle.json
    ppdm_39_fk_catalog_snowflake.json
    ppdm_39_schema_domain.json
    ppdm_39_schema_domain.pkl
    ppdm_39_schema_domain_sqlserver.json
    ppdm_39_schema_domain_sqlserver.pkl
    ppdm_39_schema_domain_oracle.json
    ppdm_39_schema_domain_oracle.pkl
    ppdm_39_schema_domain_snowflake.json
    ppdm_39_schema_domain_snowflake.pkl
) do (
    if exist "%SRC%\schema_registry\%%F" (
        copy /y "%SRC%\schema_registry\%%F" "%DEST%\schema_registry\%%F" >nul
    ) else (
        echo   MISSING: schema_registry\%%F  ^^^<^^^<^^^< CHECK THIS
    )
)

:: ── seed_catalog (CSVs only) ────────────────────────────────────────────────
echo.
echo Copying seed catalog...
mkdir "%DEST%\seed_catalog"
for %%F in ("%SRC%\seed_catalog\*.csv") do (
    copy /y "%%F" "%DEST%\seed_catalog\" >nul
)

:: ── assets ──────────────────────────────────────────────────────────────────
echo.
echo Copying assets...
mkdir "%DEST%\assets"
for %%F in (data_wrangler.png data_wrangler.ico) do (
    if exist "%SRC%\assets\%%F" (
        copy /y "%SRC%\assets\%%F" "%DEST%\assets\%%F" >nul
        echo        Copied: assets\%%F
    ) else (
        echo   MISSING: assets\%%F  ^^^<^^^<^^^< CHECK THIS
    )
)

:: ── deployment bootstrap (copy from v1 dist manually if missing) ─────────────
echo.
echo Copying deployment bootstrap files...
for %%F in (python-3.12.10-embed-amd64.zip get-pip.py extract.vbs) do (
    if exist "%SRC%\%%F" (
        copy /y "%SRC%\%%F" "%DEST%\%%F" >nul
        echo        Copied: %%F
    ) else (
        echo   MISSING: %%F  ^^^<^^^<^^^< Copy from v1 dist manually
    )
)

:: ── .env template ───────────────────────────────────────────────────────────
echo.
echo Creating .env for dist...
if exist "%SRC%\write_dist_env.py" (
    python "%SRC%\write_dist_env.py" "%SRC%" "%DEST%"
) else (
    echo   MISSING: write_dist_env.py -- .env not created
)

:: ── Done ────────────────────────────────────────────────────────────────────
echo.
echo ========================================
echo  Done. Distribution folder: %DEST%
echo ========================================
echo.
echo Checklist before compiling with Inno:
echo   1. No MISSING lines above
echo   2. assets\data_wrangler.ico exists
echo   3. python-3.12.10-embed-amd64.zip exists
echo   4. get-pip.py exists
echo   5. extract.vbs exists
echo   6. .env has LICENCE_GITHUB_TOKEN filled in
echo.
echo NOTE: ANTHROPIC_API_KEY left blank - user supplies their own.
echo.
pause
