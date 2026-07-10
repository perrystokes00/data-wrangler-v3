r"""
patch_run_h3_compute_count.py — staged 0 rows, but we don't know if the COMPUTE step wrote
anything to result.csv (step 2 is silent). This adds a count of rows written in step 2 AND
keeps the temp files on failure so they can be inspected. .bak, idempotent. py patch_run_h3_compute_count.py
"""
import os, ast, sys
P="run_h3.py"
if not os.path.exists(P): sys.exit("run_h3.py not found")
s=open(P,encoding="utf-8").read()
if "computed_rows" in s: print("already patched"); sys.exit(0)

# add a counter to the compute loop
old = '''            w.writerow([p[0]] + [row.get(c, "") or "" for c in H3COLS])
            if i % 20000 == 0:
                log(f"      {i:,}")'''
new = '''            w.writerow([p[0]] + [row.get(c, "") or "" for c in H3COLS])
            computed_rows += 1
            if i % 20000 == 0:
                log(f"      {i:,}")'''
if old not in s: sys.exit("FAILED: compute loop not found")
s=s.replace(old,new,1)

# init the counter before the loop and log after
old2='''    log("[2/4] computing H3 (r4..r7) -> result CSV …")
    to_cell, _ = h3_grids._bind_h3()'''
new2='''    log("[2/4] computing H3 (r4..r7) -> result CSV …")
    computed_rows = 0
    to_cell, _ = h3_grids._bind_h3()'''
if old2 not in s: sys.exit("FAILED: compute header not found")
s=s.replace(old2,new2,1)

# log the count right after the compute with-block (before step 3)
old3='''    log("[3/4] bcp load -> stg.dv_well_h3_stage …")'''
new3='''    log(f"      computed {computed_rows:,} rows -> result CSV")
    if computed_rows == 0:
        log("      ERROR: compute wrote 0 rows. Either h3_grids.compute_h3_row is failing "
            "for every row, or the coords CSV parsed to <3 fields. Inspect: " + result)
        _rsz = os.path.getsize(result) if os.path.exists(result) else -1
        log(f"      result CSV size: {_rsz} bytes (kept for inspection; not deleting temps)")
        return
    log("[3/4] bcp load -> stg.dv_well_h3_stage …")'''
if old3 not in s: sys.exit("FAILED: step 3 header not found")
s=s.replace(old3,new3,1)

ast.parse(s)
open(P+".bak_computecount","w",encoding="utf-8").write(open(P,encoding="utf-8").read())
open(P,"w",encoding="utf-8").write(s)
print("patched run_h3.py: logs computed row count; stops + keeps temps if compute wrote 0")
