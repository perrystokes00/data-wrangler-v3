r"""
patch_promote_held_summary.py — add a held-rows summary to run_promote's output so
rows parked on unresolved reference codes are impossible to miss.

Each per-table note already says 'held N (unresolved ...)' but nothing totals it.
This accumulates the held counts across all tables and prints, right after TOTAL:
    ⚠ 393 row(s) HELD on unresolved reference codes — open the FK review grid to
      resolve (Add the code, or Map to an existing one), then re-run promote.
When nothing is held, prints a clean confirmation instead. In place, .bak, idempotent.
py patch_promote_held_summary.py
"""
import os, re, ast, sys
P = "promote_catalog.py"
if not os.path.exists(P):
    P = os.path.join("modules", "promote_catalog.py")
if not os.path.exists(P):
    sys.exit("promote_catalog.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()
if "_held_total" in s:
    print("already patched"); sys.exit(0)

# 1) initialise a held accumulator next to the total_e/_m/_r counters.
#    Anchor on 'total_e = total_m = total_r = 0'.
init_anchor = "    total_e = total_m = total_r = 0"
if init_anchor not in s:
    sys.exit("FAILED: total counter init not found")
s = s.replace(init_anchor,
              init_anchor + "\n    _held_total = 0   # rows parked on unresolved reference FK codes",
              1)

# 2) after each per-table note is logged in the main discover loop, parse its
#    'held N' and accumulate. Anchor on the loop's log line + the total_e add.
loop_anchor = '''        log(f"{cat:30} {e:>9} {m:>8} {r:>9}  {note}")
        total_e += eligible or 0'''
loop_new = '''        log(f"{cat:30} {e:>9} {m:>8} {r:>9}  {note}")
        _hm = re.search(r"held (\\d+)", note or "")
        if _hm:
            _held_total += int(_hm.group(1))
        total_e += eligible or 0'''
if loop_anchor not in s:
    sys.exit("FAILED: per-table log/total anchor not found")
s = s.replace(loop_anchor, loop_new, 1)

# 3) print the held summary right after the TOTAL line.
total_anchor = '''    log(f"{'TOTAL':30} {total_e:>9} {total_m:>8} {total_r:>9}")'''
total_new = '''    log(f"{'TOTAL':30} {total_e:>9} {total_m:>8} {total_r:>9}")
    if _held_total:
        log(f"\\u26a0 {_held_total:,} row(s) HELD on unresolved reference codes "
            f"\\u2014 open the FK review grid to resolve (Add the code, or Map it "
            f"to an existing one), then re-run promote.")
    else:
        log("\\u2705 no rows held on reference codes.")'''
if total_anchor not in s:
    sys.exit("FAILED: TOTAL log line not found")
s = s.replace(total_anchor, total_new, 1)

# 4) ensure 're' is imported (run_promote uses it now).
if "\nimport re\n" not in s and "import re\r\n" not in s and not re.search(r"^import re$", s, re.M):
    # add near the top after the first import block
    s = s.replace("from __future__ import annotations\n",
                  "from __future__ import annotations\nimport re\n", 1) \
         if "from __future__ import annotations\n" in s else ("import re\n" + s)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: promote now prints a held-rows summary after TOTAL")
