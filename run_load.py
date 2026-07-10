"""run_load.py — load the remaining pending files directly, no UI. One process,
proven config: multi-core -> BCP fast-path. py run_load.py"""
import sys, os, urllib.parse as _u

def main():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules"))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from sqlalchemy import create_engine
    from dataview.import_data.pipeline_run import run_pipeline

    CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
            r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
    engine = create_engine("mssql+pyodbc:///?odbc_connect=" + _u.quote_plus(CONN),
                           fast_executemany=True)
    ROOT = r"C:\Users\perry\OneDrive\Documents\KSGS\LAS_Files\_selected"

    print("Loading remaining pending files (no re-scan). Ctrl-C to stop.\n")
    run_pipeline(
        engine, ROOT,
        do_scan=True,
        do_enrich=True, enrich_apply=True,
        do_capture=True,
        do_promote=True, promote_apply=True,
        parse_mode="process",     # multi-core -> LAS BCP fast-path
        single_pass=False,        # extract-skips-LAS + _stage_capture BCP (proven path)
        do_vault=False,
        do_report=True,
        ref="WELL_REF.well_ref.well_master_gold",
        log=print,
    )
    print("\nDONE.")

if __name__ == "__main__":
    import multiprocessing as _mp
    _mp.freeze_support()          # Windows spawn-safety
    main()
