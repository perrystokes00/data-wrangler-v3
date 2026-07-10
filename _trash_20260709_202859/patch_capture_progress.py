"""
patch_capture_progress.py — add a running progress message to the capture stage
(every 25 files) so long captures show '[capture] +N/total (ok X · rows Y)'
instead of going silent. Patches both the parallel pool and sequential loop in
_stage_capture. In place, .bak, idempotent.  Run: py patch_capture_progress.py
"""
import sys, ast
P = "pipeline_run.py"
s = open(P, encoding="utf-8").read()
if "[capture] +{" in s:
    print("already patched"); sys.exit(0)

# 1) parallel pool loop
par_old = (
    "            with ProcessPoolExecutor(max_workers=workers) as pool:\n"
    "                for fname, status, nrows, err in pool.map(_capture_proc_one, _args):\n"
    "                    if status == \"error\" and err:\n"
    "                        log(f\"  [x] {fname}: {str(err)[:400]}\")\n"
    "                    else:\n"
    "                        rows_total += nrows\n"
    "                        if status == \"done\" and nrows:\n"
    "                            ok += 1\n")
par_new = (
    "            with ProcessPoolExecutor(max_workers=workers) as pool:\n"
    "                _done = 0\n"
    "                for fname, status, nrows, err in pool.map(_capture_proc_one, _args):\n"
    "                    _done += 1\n"
    "                    if status == \"error\" and err:\n"
    "                        log(f\"  [x] {fname}: {str(err)[:400]}\")\n"
    "                    else:\n"
    "                        rows_total += nrows\n"
    "                        if status == \"done\" and nrows:\n"
    "                            ok += 1\n"
    "                    if _done % 25 == 0 or _done == total:\n"
    "                        log(f\"[capture] +{_done}/{total}  (ok {ok:,} \u00b7 rows {rows_total:,})\")\n")
if par_old not in s:
    print("FAILED: parallel pool loop anchor not found."); sys.exit(1)
s = s.replace(par_old, par_new, 1)

# 2) sequential loop
seq_old = (
    "    if not _did_parallel:\n"
    "        for r in files:\n"
    "            _muwi = \"\" if r[2] is None else str(r[2]).strip()\n"
    "            _capture_one(r[0], str(r[1] or \"\").lower(), _muwi, r[3])\n")
seq_new = (
    "    if not _did_parallel:\n"
    "        for _i, r in enumerate(files, 1):\n"
    "            _muwi = \"\" if r[2] is None else str(r[2]).strip()\n"
    "            _capture_one(r[0], str(r[1] or \"\").lower(), _muwi, r[3])\n"
    "            if _i % 25 == 0 or _i == total:\n"
    "                log(f\"[capture] +{_i}/{total}  (ok {ok:,} \u00b7 rows {rows_total:,})\")\n")
if seq_old not in s:
    print("FAILED: sequential loop anchor not found."); sys.exit(1)
s = s.replace(seq_old, seq_new, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: capture stage logs '[capture] +N/total (ok X · rows Y)' every 25 files")
