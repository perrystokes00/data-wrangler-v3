"""force_capture.py — call _stage_capture DIRECTLY (bypasses the pipeline file-guard)
so the .las files get their cat_* mirrors written, then promote. Clears CAPTURED_HASH
first so the 402 are eligible again. py force_capture.py"""
import sys, os, urllib.parse as _u
def main():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules"))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import pyodbc
    from sqlalchemy import create_engine
    from dataview.import_data.pipeline_run import _stage_capture
    from dataview.file_catalog.promote_catalog import run_promote, enrich_from_gold

    CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
            r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
    # clear CAPTURED_HASH so the already-'captured' 402 are eligible again
    cur = pyodbc.connect(CONN, autocommit=True).cursor()
    n = cur.execute("UPDATE file_catalog.GLOBAL_FILE_CATALOG SET CAPTURED_HASH=NULL "
                    "WHERE LOWER(FILE_EXT)='.las'").rowcount
    print(f"cleared CAPTURED_HASH on {n} .las file(s) so capture re-selects them\n")

    eng = create_engine("mssql+pyodbc:///?odbc_connect=" + _u.quote_plus(CONN),
                        fast_executemany=True)
    print("running capture directly (parallel=process)…")
    r = _stage_capture(eng, "mssql", print, workers=6, parallel=True)
    print("capture result:", r)

    print("\npromoting…")
    cn = pyodbc.connect(CONN); cn.autocommit = False; c2 = cn.cursor()
    try:
        run_promote(c2, apply=True, log=print)
        enrich_from_gold(c2, log=print)
        cn.commit(); print("committed.")
    except Exception as e:
        cn.rollback(); print("rolled back:", str(e)[:200]); raise
    finally:
        cn.close()
    print("\nDONE.")
if __name__ == "__main__":
    import multiprocessing as _mp; _mp.freeze_support(); main()
