r"""
patch_wire_segy_fastpath.py — route SEG-Y files through the new bulk fast-path in
_stage_capture, alongside the LAS one. Splits _segy_rows from the pool and calls
run_bcp_capture_segy (parallel header parse + single BULK INSERT to FILE_SEIS_HEADER),
then marks them extracted so the pool doesn't re-touch them. py patch_wire_segy_fastpath.py
"""
import sys, os, ast
P = "pipeline_run.py"
if not os.path.exists(P):
    P = os.path.join("modules", "pipeline_run.py")
if not os.path.exists(P):
    sys.exit("pipeline_run.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()
if "run_bcp_capture_segy" in s:
    print("already wired"); sys.exit(0)

# Anchor: right after the LAS fast-path block sets `files = _oth_rows`. We split
# SEG-Y out of _oth_rows and run the segy fast-path, then leave the rest to the pool.
anchor = '''                files = _oth_rows
            except Exception as _e:
                log(f"[capture] BCP fast-path failed ({str(_e)[:120]}); LAS fall back to pool")'''
inject = '''                files = _oth_rows
            except Exception as _e:
                log(f"[capture] BCP fast-path failed ({str(_e)[:120]}); LAS fall back to pool")

        # SEG-Y fast-path: header-only bulk capture (parallel parse -> one BULK
        # INSERT to FILE_SEIS_HEADER). segy_header reads only the file header +
        # a small trace-header geometry sample, never trace data, so it's fast
        # even on multi-GB files. Pulls .segy/.sgy/.seg out of the pool set.
        _segy_exts = (".segy", ".sgy", ".seg")
        _segy_rows = [r for r in files if str(r[1] or "").lower() in _segy_exts]
        if _segy_rows:
            try:
                from bcp_capture import run_bcp_capture_segy
            except Exception:
                try:
                    from modules.bcp_capture import run_bcp_capture_segy
                except Exception:
                    run_bcp_capture_segy = None
            if run_bcp_capture_segy:
                import urllib.parse as _upq2
                try:
                    _odbc2 = _upq2.unquote(engine.url.query.get("odbc_connect", "")) or None
                except Exception:
                    _odbc2 = None
                _segy_recs = [{"FILE_PATH": r[0], "INVENTORY_ID": r[4]} for r in _segy_rows]
                try:
                    _sres = run_bcp_capture_segy(_segy_recs, conn_str=_odbc2,
                                                 workers=workers, log=log)
                    _sn = sum(_sres.values())
                    rows_total += _sn
                    ok += len(_segy_rows)
                    log(f"[capture] SEG-Y fast-path (BCP): {_sn:,} header(s) "
                        f"from {len(_segy_rows):,} file(s)")
                    try:
                        from sqlalchemy import text as _t3
                        _siid = [int(r[4]) for r in _segy_rows if r[4] is not None]
                        with engine.begin() as _c3:
                            for _j in range(0, len(_siid), 1000):
                                _blk3 = ",".join(str(x) for x in _siid[_j:_j+1000])
                                if _blk3:
                                    _c3.execute(_t3(
                                        "UPDATE file_catalog.GLOBAL_FILE_CATALOG "
                                        "SET HEADER_EXTRACTED='Y', ROW_CHANGED_DATE=GETUTCDATE() "
                                        "WHERE INVENTORY_ID IN (" + _blk3 + ")"))
                    except Exception as _me3:
                        log(f"[capture] (segy mark-extracted skipped: {str(_me3)[:80]})")
                    files = [r for r in files if str(r[1] or "").lower() not in _segy_exts]
                except Exception as _se:
                    log(f"[capture] SEG-Y fast-path failed ({str(_se)[:120]}); "
                        f"SEG-Y falls back to pool")'''

if anchor not in s:
    sys.exit("FAILED: LAS fast-path tail anchor not found")
s = s.replace(anchor, inject, 1)
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: SEG-Y now routes through the bulk fast-path")
