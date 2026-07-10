"""repromote2.py — re-promote the existing cat_* rows directly (bypasses the
pipeline's 'no new files' guard). Runs run_promote() + enrich_from_gold() on the
data already captured. py repromote2.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pyodbc
from promote_catalog import run_promote, enrich_from_gold

cn = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
cn.autocommit = False
cur = cn.cursor()
try:
    print("running promote on existing cat_* rows…\n")
    run_promote(cur, apply=True, log=print)
    print("\nfilling coords from gold…")
    enrich_from_gold(cur, log=print)
    cn.commit()
    print("\ncommitted.")
except Exception as e:
    cn.rollback()
    print("rolled back:", str(e)[:300])
    raise
finally:
    cn.close()
