r"""
patch_run_h3_colwidth.py — FOUND: BCP load fails "String data, right truncation" on the
h3 columns. H3 cell IDs are 15 hex chars, staging cols are NVARCHAR(15) — zero margin, and
the Windows \r\n row terminator leaves a stray \r on the last field (h3_r7), making it 16
chars -> overflow -> ALL rows rejected. Fix: widen staging h3 cols to NVARCHAR(20) so the
load succeeds. (The real dv_well h3 cols are fine; this is only the staging mirror.)
.bak, idempotent. py patch_run_h3_colwidth.py
"""
import os, ast, sys
P="run_h3.py"
if not os.path.exists(P): sys.exit("run_h3.py not found")
s=open(P,encoding="utf-8").read()

old='coldefs = ", ".join([f"[{KEY}] NVARCHAR(80)"] + [f"[{c}] NVARCHAR(15)" for c in H3COLS])'
new='coldefs = ", ".join([f"[{KEY}] NVARCHAR(80)"] + [f"[{c}] NVARCHAR(20)" for c in H3COLS])'
if new in s: print("already patched (NVARCHAR(20))"); sys.exit(0)
if old not in s: sys.exit("FAILED: staging coldef line not found")
s=s.replace(old,new,1)
ast.parse(s)
open(P+".bak_colwidth","w",encoding="utf-8").write(open(P,encoding="utf-8").read())
open(P,"w",encoding="utf-8").write(s)
print("patched run_h3.py: staging h3 columns NVARCHAR(15) -> NVARCHAR(20)")
print("this absorbs the stray \\r from Windows line endings so BCP stops truncating.")
