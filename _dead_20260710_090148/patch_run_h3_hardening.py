r"""
patch_run_h3_hardening.py — run_h3.py step 3 ignores the BCP load return, so a silent
load failure -> 0 updated with no error (the likely cause of the '0 rows updated' run).
This: (1) drops any stale staging table before CREATE, (2) logs the BCP load row count,
(3) warns if staging is empty before the UPDATE. .bak, idempotent, verifies parse.
py patch_run_h3_hardening.py
"""
import os, ast, sys
P="run_h3.py"
if not os.path.exists(P): sys.exit("run_h3.py not found — run from app root")
s=open(P,encoding="utf-8").read()
if "loaded_rows" in s: print("already patched"); sys.exit(0)

old = '''    coldefs = ", ".join([f"[{KEY}] NVARCHAR(80)"] + [f"[{c}] NVARCHAR(15)" for c in H3COLS])
    with eng.begin() as c:
        c.execute(text(f"CREATE TABLE {STG}.dv_well_h3_stage ({coldefs})"))
    bcp([f"{STG}.dv_well_h3_stage", "in", result, "-c", "-t|", "-C", "65001",
         "-T", f"-S{SERVER}", f"-d{DATABASE}", "-q"])'''

new = '''    coldefs = ", ".join([f"[{KEY}] NVARCHAR(80)"] + [f"[{c}] NVARCHAR(15)" for c in H3COLS])
    with eng.begin() as c:
        # drop any stale staging table from a previous failed run (silent-hole guard)
        c.execute(text(f"IF OBJECT_ID('{STG}.dv_well_h3_stage') IS NOT NULL "
                       f"DROP TABLE {STG}.dv_well_h3_stage"))
        c.execute(text(f"CREATE TABLE {STG}.dv_well_h3_stage ({coldefs})"))
    loaded_rows = bcp([f"{STG}.dv_well_h3_stage", "in", result, "-c", "-t|", "-C", "65001",
         "-T", f"-S{SERVER}", f"-d{DATABASE}", "-q"])
    log(f"      staged {loaded_rows:,} rows")
    if not loaded_rows:
        log("      WARNING: 0 rows loaded into staging — BCP load produced nothing; "
            "the UPDATE will match 0. Check the result CSV and BCP output.")'''

if old not in s:
    sys.exit("FAILED: step-3 block not found (file may differ)")
s=s.replace(old,new,1)
ast.parse(s)
open(P+".bak_hardening","w",encoding="utf-8").write(open(P,encoding="utf-8").read())
open(P,"w",encoding="utf-8").write(s)
print("patched run_h3.py: drops stale staging, logs staged row count, warns on empty load")
