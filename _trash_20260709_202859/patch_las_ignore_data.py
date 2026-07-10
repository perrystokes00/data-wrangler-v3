"""
patch_las_ignore_data.py — make LAS capture read only the HEADER + curve
definitions, not the entire data section. lasio.read(..., ignore_data=True)
skips parsing every depth sample (the slow part on real MB-sized logs); capture
only stores header + one row per curve, so the samples were being parsed and
thrown away. Depth range now comes from the header STRT/STOP instead of the
(now-unread) data index. In place, .bak, idempotent.  Run: py patch_las_ignore_data.py
"""
import sys, ast
P = "worker_core.py"
s = open(P, encoding="utf-8").read()
if "ignore_data=True" in s:
    print("already patched"); sys.exit(0)

# 1) skip the data section
old_read = "    las = lasio.read(fpath)\n"
new_read = "    las = lasio.read(fpath, ignore_data=True)   # header + curve defs only (skip samples)\n"
if old_read not in s:
    print("FAILED: lasio.read line not found."); sys.exit(1)
s = s.replace(old_read, new_read, 1)

# 2) depth range from header STRT/STOP (data index is empty when ignore_data=True)
old_depth = (
    "    try:\n"
    "        _idx = las.index\n"
    "        d_start = float(_idx[0])  if len(_idx) else None\n"
    "        d_stop  = float(_idx[-1]) if len(_idx) else None\n"
    "    except Exception:\n"
    "        d_start = d_stop = None\n")
new_depth = (
    "    def _fnum(v):\n"
    "        try:\n"
    "            return float(str(v).strip())\n"
    "        except Exception:\n"
    "            return None\n"
    "    d_start = _fnum(_wv(\"STRT\", \"START\"))\n"
    "    d_stop  = _fnum(_wv(\"STOP\"))\n")
if old_depth not in s:
    print("FAILED: depth-frame block not found."); sys.exit(1)
s = s.replace(old_depth, new_depth, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: LAS capture reads header only (ignore_data=True); depth from STRT/STOP")
