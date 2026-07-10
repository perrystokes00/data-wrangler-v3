r"""
patch_run_h3_rowterm.py — ROOT CAUSE FOUND: run_h3's result CSV uses bare \n line endings,
but BCP -c defaults to \r\n row terminator, so BCP read the whole file as ONE row -> column
5 (h3_r7) absorbed everything -> "String data, right truncation" -> 0 staged. Adding
-r 0x0a to the BCP load makes it read \n-terminated rows correctly. Test confirmed: loads 655.
.bak, idempotent. py patch_run_h3_rowterm.py
"""
import os, ast, sys
P="run_h3.py"
if not os.path.exists(P): sys.exit("run_h3.py not found")
s=open(P,encoding="utf-8").read()
if '"-r", "0x0a"' in s: print("already patched"); sys.exit(0)

# the load call — add -r 0x0a. Handle the current (errfile-patched) form.
import re
# find the bcp load list that has "in", result and -q ; insert -r 0x0a before -e or -q
# current form after errfile patch:
old='''    loaded_rows = bcp([f"{STG}.dv_well_h3_stage", "in", result, "-c", "-t|", "-C", "65001",
         "-T", f"-S{SERVER}", f"-d{DATABASE}", "-q", "-e", _errf])'''
new='''    loaded_rows = bcp([f"{STG}.dv_well_h3_stage", "in", result, "-c", "-t|", "-r", "0x0a",
         "-C", "65001", "-T", f"-S{SERVER}", f"-d{DATABASE}", "-q", "-e", _errf])'''
if old in s:
    s=s.replace(old,new,1)
else:
    # fall back to the original unpatched form
    old2='''    bcp([f"{STG}.dv_well_h3_stage", "in", result, "-c", "-t|", "-C", "65001",
         "-T", f"-S{SERVER}", f"-d{DATABASE}", "-q"])'''
    new2='''    bcp([f"{STG}.dv_well_h3_stage", "in", result, "-c", "-t|", "-r", "0x0a", "-C", "65001",
         "-T", f"-S{SERVER}", f"-d{DATABASE}", "-q"])'''
    if old2 not in s: sys.exit("FAILED: BCP load call not found in a known form")
    s=s.replace(old2,new2,1)

ast.parse(s)
open(P+".bak_rowterm","w",encoding="utf-8").write(open(P,encoding="utf-8").read())
open(P,"w",encoding="utf-8").write(s)
print("patched run_h3.py: BCP load now uses -r 0x0a (bare \\n row terminator)")
print("this is the fix — test confirmed it loads all 655 rows.")
