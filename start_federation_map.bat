@echo off
echo ═@echo off
cd /d "C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3"
call venv\Scripts\activate
set SNOWFLAKE_ACCOUNT=YDWXNCV-VL88062
set SNOWFLAKE_USER=PMSTOKES00
set SNOWFLAKE_PASSWORD=Wrangler0101#$
echo Starting Federation Map on port 8503...
streamlit run federation_map.py --server.port 8503