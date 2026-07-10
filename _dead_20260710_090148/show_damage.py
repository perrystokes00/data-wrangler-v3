"""show_damage.py — dump the damaged region of promote_catalog.py so we can splice
the pristine promote_seismic back in. Shows the lines around where 'def promote_seismic'
should be (between promote_field and promote_las_catalog). writes to file. py show_damage.py"""
import os
P = "promote_catalog.py"
if not os.path.exists(P): P = os.path.join("modules","promote_catalog.py")
lines = open(P, encoding="utf-8").read().splitlines()

# find promote_field end and promote_las_catalog start — promote_seismic belongs between
def find(sig):
    for i,l in enumerate(lines):
        if l.startswith(sig): return i
    return -1
pf  = find("def promote_field")
plc = find("def promote_las_catalog")
pwg = find("def promote_well_geog")
print(f"def promote_field:      line {pf+1}")
print(f"def promote_well_geog:  line {pwg+1}")
print(f"def promote_las_catalog:line {plc+1}")
print(f"def promote_seismic:    {'MISSING' if find('def promote_seismic')<0 else find('def promote_seismic')+1}")

# dump from promote_field to promote_las_catalog (the region that should contain seismic)
lo = pf if pf>=0 else 0
hi = plc if plc>=0 else len(lines)
OUT = r"C:\Bulk\reports\damage.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT,"w",encoding="utf-8") as f:
    for i in range(max(0,lo), min(len(lines), hi+3)):
        f.write(f"{i+1:5} {lines[i]}\n")
print(f"\n>>> dumped lines {lo+1}..{hi+3} to {OUT} — upload it")
print("(this is the region where promote_seismic was eaten)")
