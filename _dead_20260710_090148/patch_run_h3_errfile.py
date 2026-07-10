r"""
patch_run_h3_errfile.py — BCP load stages 0 silently. Add an -e error file to the load,
log the error file contents, and KEEP the result CSV when staging is 0. This surfaces the
real per-row BCP error (which exit-code 0 hides). .bak, idempotent. py patch_run_h3_errfile.py
"""
import os, ast, sys
P="run_h3.py"
if not os.path.exists(P): sys.exit("run_h3.py not found")
s=open(P,encoding="utf-8").read()
if "h3_load_err" in s: print("already patched"); sys.exit(0)

# replace the load call (already hardened form with loaded_rows) to add -e and keep-on-empty
old='''    loaded_rows = bcp([f"{STG}.dv_well_h3_stage", "in", result, "-c", "-t|", "-C", "65001",
         "-T", f"-S{SERVER}", f"-d{DATABASE}", "-q"])
    log(f"      staged {loaded_rows:,} rows")
    if not loaded_rows:
        log("      WARNING: 0 rows loaded into staging — BCP load produced nothing; "
            "the UPDATE will match 0. Check the result CSV and BCP output.")'''
new='''    _errf = os.path.join(tempfile.gettempdir(), "h3_load_err.txt")
    loaded_rows = bcp([f"{STG}.dv_well_h3_stage", "in", result, "-c", "-t|", "-C", "65001",
         "-T", f"-S{SERVER}", f"-d{DATABASE}", "-q", "-e", _errf])
    log(f"      staged {loaded_rows:,} rows")
    if not loaded_rows:
        log("      WARNING: 0 rows loaded into staging.")
        try:
            if os.path.exists(_errf) and os.path.getsize(_errf):
                log("      --- BCP error file (first 600 chars) ---")
                log(open(_errf, encoding="utf-8", errors="replace").read()[:600])
        except Exception as _e:
            log(f"      (couldn't read error file: {_e})")
        log(f"      result CSV KEPT for inspection: {result}")
        log(f"      first 3 result lines:")
        try:
            with open(result, encoding="utf-8", errors="replace") as _rf:
                for _i, _ln in enumerate(_rf):
                    if _i >= 3: break
                    log(f"        {_ln.rstrip()!r}")
        except Exception as _e:
            log(f"        (couldn't read result: {_e})")
        return  # stop before deleting temps so you can inspect'''
if old not in s: sys.exit("FAILED: hardened load block not found — apply patch_run_h3_hardening first")
s=s.replace(old,new,1)
ast.parse(s)
open(P+".bak_errfile","w",encoding="utf-8").write(open(P,encoding="utf-8").read())
open(P,"w",encoding="utf-8").write(s)
print("patched run_h3.py: BCP load now writes -e error file, logs it, and keeps CSV on 0-stage")
