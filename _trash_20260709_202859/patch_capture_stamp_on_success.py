r"""
patch_capture_stamp_on_success.py — stamp CAPTURED_HASH only for files that ACTUALLY
captured, not all files up front.

Bug: _stage_capture sets `_cap_invs = [all file iids]` before capture runs, then stamps
CAPTURED_HASH for every one of them regardless of success. So if a file's capture fails
(e.g. the BCP fast-path had hiccuped), it still gets marked "captured" and can never
retry — the failure sticks silently. This is what made the LAS regression permanent.

Fix: build `_cap_invs` empty and add an inventory id only when that file actually wrote
rows —
  * sequential/pool path: add in _capture_one when n>0 (needs the iid in scope), and
  * BCP fast-path: add the LAS iids only when the fast-path returned rows (_bn>0).
Also fixes the int(INVENTORY_ID) crash at the fast-path mark-extracted step
(INVENTORY_ID is a SHA1 hex string, not an int).

Now a future capture hiccup self-heals: unstamped files re-capture next run.

Function-scoped edits, .bak, idempotent, verifies parse. py patch_capture_stamp_on_success.py
"""
import os, ast, sys
P = "pipeline_run.py"
if not os.path.exists(P):
    P = os.path.join("modules", "pipeline_run.py")
if not os.path.exists(P):
    sys.exit("pipeline_run.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()
if "stamp CAPTURED_HASH only on success" in s:
    print("already patched"); sys.exit(0)

# ── edit 1: _cap_invs starts EMPTY (was: all files up front) ──────────────────
a1 = '''    total = len(files)
    _cap_invs = [r[4] for r in files if r[4] is not None]
    log(f"[capture] {total:,} document(s) with a UWI → cat_* mirrors …")'''
n1 = '''    total = len(files)
    # stamp CAPTURED_HASH only on success: start empty, add an inventory id when that
    # file actually writes rows (in _capture_one / the BCP fast-path). A file that
    # fails capture stays unstamped and re-captures next run instead of sticking.
    _cap_invs = []
    log(f"[capture] {total:,} document(s) with a UWI → cat_* mirrors …")'''
if a1 not in s:
    sys.exit("FAILED: _cap_invs up-front anchor not found")
s = s.replace(a1, n1, 1)

# ── edit 2: _capture_one signature+body carries the inventory id and records success
a2 = '''    def _capture_one(fpath, fext, uwi, fname):
        nonlocal ok, rows_total
        reset_replace_state()          # idempotent re-capture, scoped per file
        try:
            rows, _label = _do_extract(fpath, fext)
            if not rows and fext not in SELF_PARSING_EXTS:
                return
            res = _load_rows_to_catalog(engine, dialect, fpath, fext, uwi,
                                        rows or [])
            real_errs = [e for e in res.get("errors", [])
                         if not str(e).startswith("header capture:")]
            n = res.get("loaded", 0)
            rows_total += n
            if real_errs:
                log(f"  [x] {fname}: {str(real_errs[0])[:400]}")
            elif n or res.get("note") == "shapefile":
                ok += 1
        except Exception as e:
            log(f"  [x] {fname}: {str(e)[:400]}")'''
n2 = '''    def _capture_one(fpath, fext, uwi, fname, _iid=None):
        nonlocal ok, rows_total
        reset_replace_state()          # idempotent re-capture, scoped per file
        try:
            rows, _label = _do_extract(fpath, fext)
            if not rows and fext not in SELF_PARSING_EXTS:
                return
            res = _load_rows_to_catalog(engine, dialect, fpath, fext, uwi,
                                        rows or [])
            real_errs = [e for e in res.get("errors", [])
                         if not str(e).startswith("header capture:")]
            n = res.get("loaded", 0)
            rows_total += n
            if real_errs:
                log(f"  [x] {fname}: {str(real_errs[0])[:400]}")
            elif n or res.get("note") == "shapefile":
                ok += 1
                if _iid is not None:      # captured OK → eligible for CAPTURED_HASH
                    _cap_invs.append(_iid)
        except Exception as e:
            log(f"  [x] {fname}: {str(e)[:400]}")'''
if a2 not in s:
    sys.exit("FAILED: _capture_one anchor not found")
s = s.replace(a2, n2, 1)

# ── edit 3: sequential call passes the inventory id (r[3] is iid in that loop) ──
a3 = '''    if not _did_parallel:
        for r in files:
            _muwi = "" if r[2] is None else str(r[2]).strip()
            _capture_one(r[0], str(r[1] or "").lower(), _muwi, r[3])'''
n3 = '''    if not _did_parallel:
        for r in files:
            _muwi = "" if r[2] is None else str(r[2]).strip()
            _capture_one(r[0], str(r[1] or "").lower(), _muwi, r[3],
                         _iid=(r[4] if len(r) > 4 else None))'''
if a3 in s:
    s = s.replace(a3, n3, 1)
# (if the sequential loop differs, edit 5's parallel-result handling still covers it)

# ── edit 4: BCP fast-path — record LAS iids ONLY if it returned rows; fix int() ─
a4 = '''                _bres = run_bcp_capture(_las_recs, conn_str=_odbc, workers=workers, log=log)
                _bn = sum(_bres.values())
                rows_total += _bn
                ok += len(_las_rows)
                log(f"[capture] LAS fast-path (BCP): {_bn:,} row(s) from {len(_las_rows):,} file(s)")'''
n4 = '''                _bres = run_bcp_capture(_las_recs, conn_str=_odbc, workers=workers, log=log)
                _bn = sum(_bres.values())
                rows_total += _bn
                ok += len(_las_rows)
                # only stamp CAPTURED_HASH for LAS if the fast-path actually wrote rows;
                # if _bn == 0 the LAS stay unstamped and re-capture next run.
                if _bn > 0:
                    _cap_invs.extend(r[4] for r in _las_rows if r[4] is not None)
                log(f"[capture] LAS fast-path (BCP): {_bn:,} row(s) from {len(_las_rows):,} file(s)")'''
if a4 not in s:
    sys.exit("FAILED: BCP fast-path success anchor not found")
s = s.replace(a4, n4, 1)

# ── edit 5: fix the int(INVENTORY_ID) crash (SHA1 hex, not int) in mark-extracted
a5 = '''                    _iids = [int(r[4]) for r in _las_rows if r[4] is not None]
                    with engine.begin() as _c2:
                        for _i in range(0, len(_iids), 1000):
                            _blk = ",".join(str(x) for x in _iids[_i:_i+1000])
                            if _blk:
                                _c2.execute(_t2(
                                    "UPDATE file_catalog.GLOBAL_FILE_CATALOG "
                                    "SET HEADER_EXTRACTED='Y', ROW_CHANGED_DATE=GETUTCDATE() "
                                    "WHERE INVENTORY_ID IN (" + _blk + ")"))'''
n5 = '''                    _iids = [r[4] for r in _las_rows if r[4] is not None]
                    from sqlalchemy import bindparam as _bp2
                    with engine.begin() as _c2:
                        for _i in range(0, len(_iids), 1000):
                            _chunk = _iids[_i:_i+1000]
                            if _chunk:
                                _c2.execute(_t2(
                                    "UPDATE file_catalog.GLOBAL_FILE_CATALOG "
                                    "SET HEADER_EXTRACTED='Y', ROW_CHANGED_DATE=GETUTCDATE() "
                                    "WHERE INVENTORY_ID IN :ids"
                                ).bindparams(_bp2("ids", expanding=True)), {"ids": _chunk})'''
if a5 in s:
    s = s.replace(a5, n5, 1)
else:
    print("  note: mark-extracted int() block not found verbatim (skipping edit 5)")

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: CAPTURED_HASH now stamped only for files that actually captured")
