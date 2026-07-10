"""recapture.py — now that MATCHED_UWI is set on the 402 files, run capture+promote
directly (bypasses the pipeline file-guard) so the cat_* rows get written and
promoted. py recapture.py"""
import sys, os, urllib.parse as _u
def main():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules"))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from sqlalchemy import create_engine
    from dataview.import_data.pipeline_run import run_pipeline
    CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
            r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
    eng = create_engine("mssql+pyodbc:///?odbc_connect=" + _u.quote_plus(CONN),
                        fast_executemany=True)
    ROOT = r"C:\Users\perry\OneDrive\Documents\KSGS\LAS_Files\_selected"
    print("re-capturing the now-resolved files (no re-scan)…\n")
    run_pipeline(
        eng, ROOT,
        do_scan=False,            # use the existing catalog (UWIs now set)
        do_enrich=False,          # already enriched
        do_capture=True,          # <-- write cat_* now that MATCHED_UWI is populated
        do_promote=True, promote_apply=True,
        parse_mode="process", single_pass=False,
        do_vault=False, do_report=True,
        ref="WELL_REF.well_ref.well_master_gold", log=print)
    print("\nDONE.")
if __name__ == "__main__":
    import multiprocessing as _mp; _mp.freeze_support(); main()
