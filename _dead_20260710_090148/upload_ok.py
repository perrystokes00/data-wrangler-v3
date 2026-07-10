import snowflake.connector, os, time
from pathlib import Path
conn = snowflake.connector.connect(
    account='YDWXNCV-VL88062',
    user='PMSTOKES00',
    password=os.environ['SNOWFLAKE_PASSWORD'],
    database='WELL_FEDERATION',
    warehouse='WV_WH',
    role='ACCOUNTADMIN')
cur = conn.cursor()
csv_path = r'C:\Bulk\snowflake_export\raw_ok_well.csv'.replace('\\','/')
cur.execute('USE SCHEMA RAW_OK')
cur.execute('CREATE STAGE IF NOT EXISTS RAW_OK.LOAD_STAGE')
cur.execute('TRUNCATE TABLE IF EXISTS RAW_OK.WELL')
print('Uploading...', flush=True)
t0 = time.time()
cur.execute(f"PUT 'file://{csv_path}' @RAW_OK.LOAD_STAGE AUTO_COMPRESS=TRUE OVERWRITE=TRUE")
print(f'PUT done ({time.time()-t0:.1f}s)', flush=True)
cur.execute("""
    COPY INTO RAW_OK.WELL
    FROM @RAW_OK.LOAD_STAGE/raw_ok_well.csv.gz
    FILE_FORMAT = (TYPE='CSV' FIELD_DELIMITER=',' SKIP_HEADER=1
                   FIELD_OPTIONALLY_ENCLOSED_BY=NONE NULL_IF=('') EMPTY_FIELD_AS_NULL=TRUE)
    ON_ERROR='CONTINUE'
""")
print(f'COPY done ({time.time()-t0:.1f}s)', flush=True)
cur.execute('SELECT COUNT(*) FROM RAW_OK.WELL')
print(f'Loaded: {cur.fetchone()[0]:,} rows')
cur.close()
conn.close()
