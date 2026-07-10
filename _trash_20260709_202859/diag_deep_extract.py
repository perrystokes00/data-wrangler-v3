"""diag_deep_extract.py — run the deep-extraction chain on the ANADARKO 1H sample
files and report EXACTLY what each loader returns (rows loaded / errors / skip).
Pinpoints why 'extracted but not promoted'. Run from the app dir:
  py diag_deep_extract.py <folder_with_the_4_files>
  (defaults to the training test_crawl sample_office folder if present)"""
import sys, os, importlib

FOLDER = sys.argv[1] if len(sys.argv) > 1 else "."
# the four sample files (match by suffix so exact names/paths don't matter)
wanted = {
    ".xlsx": "formation tops",
    ".csv":  "production",
    ".pdf":  "directional survey",
    ".docx": "completion",
}

# build engine the same way the app does
def _engine():
    from sqlalchemy import create_engine
    import urllib.parse as up
    odbc = ("DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\\SQLEXPRESS;"
            "DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
    return create_engine("mssql+pyodbc:///?odbc_connect=" + up.quote_plus(odbc))

def find_files(folder):
    hits = {}
    for root, _, files in os.walk(folder):
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext in wanted and ext not in hits:
                hits[ext] = os.path.join(root, fn)
    return hits

def main():
    eng = _engine()
    files = find_files(FOLDER)
    if not files:
        print(f"no sample files found under {FOLDER}")
        print("pass the folder holding the ANADARKO files:  py diag_deep_extract.py <folder>")
        return
    try:
        import worker_core as wc
    except Exception as e:
        print("cannot import worker_core:", e); return

    for ext, label in wanted.items():
        p = files.get(ext)
        print("="*66)
        print(f"{label.upper()}  ({ext})")
        if not p:
            print("   (file not found in folder)"); continue
        print("   file:", os.path.basename(p))
        try:
            rec = {"FILE_PATH": p, "FILE_EXT": ext,
                   "FILE_NAME": os.path.basename(p),
                   "UWI": "", "MATCHED_UWI": "", "INVENTORY_ID": None}
            res = wc.process_file(eng, rec)
            print("   status      :", getattr(res, "status", "?"))
            print("   report type :", getattr(res, "rt", "?"))
            print("   rows_written:", getattr(res, "rows_written", "?"))
            if getattr(res, "error", None):
                print("   ERROR       :", str(res.error)[:200])
            if getattr(res, "detail", None):
                print("   detail      :", res.detail)
        except Exception as e:
            import traceback
            print("   EXCEPTION:", e)
            print(traceback.format_exc()[-600:])

if __name__ == "__main__":
    main()
