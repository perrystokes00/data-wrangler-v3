# repromote.py — promote only, against the existing cat_* rows
import sys, os, urllib.parse as _u
def main():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules"))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from sqlalchemy import create_engine
    from pipeline_run import run_pipeline
    CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
            r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
    eng = create_engine("mssql+pyodbc:///?odbc_connect=" + _u.quote_plus(CONN), fast_executemany=True)
    run_pipeline(eng, r"C:\Users\perry\OneDrive\Documents\KSGS\LAS_Files\_selected",
                 do_scan=False, do_enrich=False, do_capture=False,
                 do_promote=True, promote_apply=True, do_vault=False, log=print)
if __name__ == "__main__":
    import multiprocessing as _mp; _mp.freeze_support(); main()
