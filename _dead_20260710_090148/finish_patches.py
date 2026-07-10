"""
finish_patches.py — apply ALL remaining loader fixes to the deployed files in one
shot, self-contained (no other patch_*.py needed). Run in the app folder.
Idempotent, writes .bak.  py finish_patches.py
Fixes:
  worker_core.py    - _valid_uwi gate + header-UWI-only-if-valid fallback
  page_workbench.py - extract-stage LAS read header-only (ignore_data)
"""
import os, ast

def _write(P, orig, s, msg_ok, msg_same):
    if s == orig:
        return msg_same
    ast.parse(s)
    open(P + ".bak", "w", encoding="utf-8").write(orig)
    open(P, "w", encoding="utf-8").write(s)
    return msg_ok

def patch_worker_core():
    P = "worker_core.py"
    if not os.path.exists(P):
        return "worker_core.py NOT FOUND (run in app folder)"
    s = orig = open(P, encoding="utf-8").read()

    if "_valid_uwi" not in s:
        helper = ('def _valid_uwi(uwi):\n'
                  '    """First 10 digits form a plausible API (state 01-62)."""\n'
                  '    if not uwi:\n        return False\n'
                  '    d = "".join(ch for ch in str(uwi) if ch.isdigit())\n'
                  '    if len(d) < 10:\n        return False\n'
                  '    try:\n        return 1 <= int(d[:2]) <= 62\n'
                  '    except ValueError:\n        return False\n\n\n')
        a = "def _do_las(engine, fpath, uwi, inv, say) -> FileResult:\n"
        if a in s:
            s = s.replace(a, helper + a, 1)

    base = ("    if _hdr_uwi:\n"
            "        uwi = _hdr_uwi      # header UWI wins — it's the real well identity\n")
    fallback = ("    if _hdr_uwi and _valid_uwi(_hdr_uwi):\n"
                "        uwi = _hdr_uwi      # header UWI wins ONLY if it's a valid API\n"
                "    # else keep the passed-in MATCHED_UWI (crosswalk-stamped)\n")
    gate = ("\n    if not _valid_uwi(uwi):\n"
            "        say(f\"skip (invalid UWI {uwi!r}): {fpath}\")\n"
            "        res.status = \"skip\"\n"
            "        res.detail[\"note\"] = f\"invalid UWI: {uwi!r}\"\n"
            "        return res\n")
    if "header UWI wins ONLY if" not in s and base in s:
        has_gate = "if not _valid_uwi(uwi):" in s
        s = s.replace(base, fallback + ("" if has_gate else gate), 1)

    return _write(P, orig, s, "worker_core.py PATCHED (gate + fallback)",
                  "worker_core.py already correct")

def patch_page_workbench():
    P = "page_workbench.py"
    if not os.path.exists(P):
        return "page_workbench.py NOT FOUND"
    s = orig = open(P, encoding="utf-8").read()
    if "ignore_data=True" in s:
        return "page_workbench.py already header-only"

    old_read = ('                inv = well_info.get("inventory_id")\n'
                '                las = lasio.read(fpath)\n')
    new_read = ('                inv = well_info.get("inventory_id")\n'
                '                las = lasio.read(fpath, ignore_data=True)   # header + curve defs only\n')
    if old_read in s:
        s = s.replace(old_read, new_read, 1)

    old_depth = (
        "                # depth frame from the LAS index (cheap; no arrays retained)\n"
        "                try:\n"
        "                    _idx = las.index\n"
        "                    d_start = float(_idx[0])  if len(_idx) else None\n"
        "                    d_stop  = float(_idx[-1]) if len(_idx) else None\n"
        "                    s_count = int(len(_idx))\n"
        "                except Exception:\n"
        "                    d_start = d_stop = None\n"
        "                    s_count = 0\n")
    new_depth = (
        "                # depth frame + sample count from the header (ignore_data)\n"
        "                def _fnum(*keys):\n"
        "                    try:\n"
        "                        return float(str(_wv(*keys)).strip())\n"
        "                    except Exception:\n"
        "                        return None\n"
        "                d_start = _fnum(\"STRT\", \"START\")\n"
        "                d_stop  = _fnum(\"STOP\")\n"
        "                _step   = _fnum(\"STEP\")\n"
        "                try:\n"
        "                    s_count = (int(round((d_stop - d_start) / _step)) + 1\n"
        "                               if (d_start is not None and d_stop is not None\n"
        "                                   and _step) else 0)\n"
        "                except Exception:\n"
        "                    s_count = 0\n")
    if old_depth in s:
        s = s.replace(old_depth, new_depth, 1)

    if "ignore_data=True" not in s:
        return "page_workbench.py: read anchor not found — paste the lines around " \
               "'las = lasio.read(fpath)' near the extract stage and I'll match it"
    return _write(P, orig, s, "page_workbench.py PATCHED (extract header-only)",
                  "page_workbench.py unchanged")

print(patch_worker_core())
print(patch_page_workbench())

def has(p, m):
    return os.path.exists(p) and m in open(p, encoding="utf-8", errors="replace").read()
print("\nVERIFY:")
print("  worker_core UWI fallback  :", has("worker_core.py", "header UWI wins ONLY if"))
print("  worker_core gate present  :", has("worker_core.py", "_valid_uwi"))
print("  page_workbench header-only:", has("page_workbench.py", "ignore_data=True"))
