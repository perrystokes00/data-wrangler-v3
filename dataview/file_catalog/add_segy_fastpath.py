r"""
add_segy_fastpath.py — add a SEG-Y bulk fast-path to bcp_capture.py, mirroring the
LAS one: parse headers in parallel (dependency-free segy_header.read_segy_header,
which reads only the 3600-byte header + a small trace-header geometry sample — never
the trace data), collect FILE_SEIS_HEADER row dicts, then ONE BULK INSERT via the
existing _load_table. py add_segy_fastpath.py
"""
import os, sys, ast
P = "bcp_capture.py"
if not os.path.exists(P):
    sys.exit("bcp_capture.py not found (run in outputs)")
s = open(P, encoding="utf-8").read()
if "parse_segy_rows" in s:
    print("already added"); sys.exit(0)

# Append the SEG-Y worker + loader at the end of the module (before the __main__
# benchmark block if present; simplest: insert before the standalone benchmark).
addition = '''

# ── SEG-Y fast-path ──────────────────────────────────────────────────────────
# Header-only capture: segy_header.read_segy_header reads the 3600-byte file
# header + up to ~50 trace headers for the CDP bbox — never the trace samples —
# so even multi-GB SEG-Y files parse in ms. Produces one FILE_SEIS_HEADER row per
# file, bulk-loaded in a single INSERT (same _load_table path LAS uses).
import uuid as _uuid_segy

SEIS_TABLE = "FILE_SEIS_HEADER"

def parse_segy_rows(arg):
    """Worker: (fpath, inv) -> {'FILE_SEIS_HEADER': [row]} or empty on failure.
    No DB access. Uses the dependency-free header reader (header-only)."""
    fpath, inv, *_ = arg
    try:
        # import inside the worker (spawn-safe on Windows)
        try:
            from dataview.file_catalog.segy_header import read_segy_header
        except Exception:
            from dataview.file_catalog.segy_header import read_segy_header
    except Exception:
        return {SEIS_TABLE: []}
    try:
        h = read_segy_header(fpath, max_geom_traces=50)   # fewer seeks: bbox stays representative
    except Exception:
        return {SEIS_TABLE: []}
    if not h or not h.get("ok"):
        return {SEIS_TABLE: []}

    # survey name: from the textual header (segy_header leaves it in notes/text);
    # fall back to the filename stem so a survey always has a name for promote.
    import os as _os, re as _re
    survey = ""
    txt = h.get("textual_header") or ""
    m = _re.search(r"(?:LINE|SURVEY|PROJECT|NAME)[:\\s]+([^\\r\\n]+?)\\s*$",
                   txt, _re.IGNORECASE | _re.MULTILINE)
    if m:
        survey = m.group(1).strip()[:255]
    if not survey:
        survey = _os.path.splitext(_os.path.basename(fpath))[0][:255]

    def _rng(pair, i):
        return pair[i] if (pair and pair[i] is not None) else None

    ilr = h.get("inline_range");    xlr = h.get("crossline_range")
    cxr = h.get("cdp_x_range");     cyr = h.get("cdp_y_range")
    hid = _uuid_segy.uuid5(_uuid_segy.NAMESPACE_URL,
                           str(inv) if inv is not None else fpath).hex.upper()
    row = {
        "SEIS_HEADER_ID": hid,
        "INVENTORY_ID":   inv,
        "SURVEY_NAME":    survey,
        "SEIS_SET_TYPE":  h.get("dims") or None,
        "SAMPLE_INTERVAL": h.get("sample_interval_us"),
        "TRACE_COUNT":    h.get("n_traces"),
        "IL_MIN": _rng(ilr, 0), "IL_MAX": _rng(ilr, 1),
        "XL_MIN": _rng(xlr, 0), "XL_MAX": _rng(xlr, 1),
        # CDP X/Y bbox -> the LON/LAT bbox columns (best-effort; these are survey
        # coords, not necessarily WGS84 — promote/geo can reproject if EPSG known)
        "BBOX_MIN_LON": _rng(cxr, 0), "BBOX_MAX_LON": _rng(cxr, 1),
        "BBOX_MIN_LAT": _rng(cyr, 0), "BBOX_MAX_LAT": _rng(cyr, 1),
        "EXTRACTED_BY": "DataWrangler",
    }
    return {SEIS_TABLE: [row]}


def run_bcp_capture_segy(recs, conn_str=None, workers=6, log=print):
    """Parallel-parse SEG-Y headers -> one BULK INSERT into FILE_SEIS_HEADER.
    recs = [{"FILE_PATH":.., "INVENTORY_ID":..}, ...]. Mirrors run_bcp_capture."""
    import pyodbc
    conn_str = conn_str or DEV_CONN
    args = [(r.get("FILE_PATH") or r.get("file_path"),
             r.get("INVENTORY_ID") or r.get("inventory_id")) for r in recs]
    rows = []
    t0 = time.time()
    _n = len(args)
    _step = max(1, _n // 8)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for _i, out in enumerate(ex.map(parse_segy_rows, args), 1):
            rows.extend(out.get(SEIS_TABLE, []))
            if _i % _step == 0 or _i == _n:
                log(f"[bcp-segy] parsing {_i:,}/{_n:,} headers… ({time.time()-t0:.0f}s)")
    t_parse = time.time() - t0
    log(f"[bcp-segy] parsed {len(rows):,} header(s) from {_n:,} file(s) in {t_parse:.1f}s")
    if not rows:
        return {SEIS_TABLE: 0}
    cn = pyodbc.connect(conn_str); cn.autocommit = False
    cur = cn.cursor(); cur.execute("SET LOCK_TIMEOUT 15000")
    try:
        n = _load_table(cur, SEIS_TABLE, rows, log, upsert_key="SEIS_HEADER_ID")
        cn.commit()
    except Exception as e:
        cn.rollback(); log(f"[bcp-segy] load error, rolled back: {e}"); raise
    finally:
        cn.close()
    log(f"[bcp-segy] loaded FILE_SEIS_HEADER={n:,} in {time.time()-t0-t_parse:.1f}s")
    return {SEIS_TABLE: n}

'''

# insert before the standalone benchmark/cleanup section if present, else append
marker = "# ── standalone benchmark / cleanup"
if marker in s:
    s = s.replace(marker, addition + "\n" + marker, 1)
else:
    s = s.rstrip() + "\n" + addition

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("added parse_segy_rows + run_bcp_capture_segy to bcp_capture.py")
