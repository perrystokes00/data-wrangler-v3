r"""
enrich_file_headers.py  —  Data Wrangler v3
================================================================================
Post-cataloging enrichment of FILE_WELL_HEADER / FILE_SEIS_HEADER from the
federated well master (WELL_REF.well_ref.WELL_MASTER).

EVERYTHING runs server-side. Both tables are on the same SQL Express instance,
so the match is a cross-database JOIN. NAME_NORM and UWI14 are computed in T-SQL
on the (small) header side, so the join still seeks the master's indexes. No
rows move through pyodbc — Python only issues statements and reads back the
proposed changes for the audit. The 4M-row master is never pulled to the client.

Passes
------
  0. CURATE UWI14 — add a persisted CHAR(14) UWI14 column on FILE_WELL_HEADER and
     fill it from the raw UWI (strip -_./ and spaces, require numeric & >=10, then
     pad/truncate to 14). NULL means the UWI field isn't a real API — flagged for
     review, raw UWI left untouched as provenance. Passes 1-2 then key off this
     stored column instead of recomputing the normalisation on every run. The
     column/index/populate happen only on a live run; --dry-run just previews counts.
  1. RESOLVE MISSING UWI — headers with a blank UWI but a name are joined to the
     master on NAME_NORM. One well -> taken; several -> tie-broken by agreement
     on county/state/operator/field (1 pt) and total depth ±tol / spud date
     (2 pts). Written only when the winner is unambiguous.
  2. FILL BLANK ATTRIBUTES — headers with a UWI (original or resolved) get blank
     columns filled from the master (unambiguous values only; never overwrites).
  3. SEIS SURVEY FROM FILE NAME — blank SURVEY_NAME derived from the file name.

Reverse capture (read-only on the reference)
--------------------------------------------
For every header whose *own* extracted UWI is a real API (gated on the raw UWI,
so name-resolved keys never qualify), record the fields where the document holds
a value the reference is MISSING entirely (no master source supplies it). These
gap-fill candidates accumulate in file_catalog.DOC_CONTRIBUTION (deduped, with
provenance: UWI14, field, doc value, source file) ready to push to Snowflake as a
document-derived federation source later. It is additive only — conflicts (both
present, disagree) are deliberately not captured here; that's a later review pass.
--dry-run stages the candidates to CSV but does not write DOC_CONTRIBUTION.

Safety: --dry-run runs the read-only report SELECTs and writes the CSV audit but
no UPDATE. Suspect UWIs and the all-zeros key are excluded.

Usage
-----
    py enrich_file_headers.py --dry-run
    py enrich_file_headers.py
    py enrich_file_headers.py --depth-tol 100 --no-seis

Requires:  pip install pyodbc
"""
import argparse
import csv
import os
import sys
import time
from collections import defaultdict
from datetime import datetime

try:
    import pyodbc
except ImportError:
    pyodbc = None

DEFAULT_SERVER = r"PERRY\SQLEXPRESS"
DEFAULT_DB     = "DataView"
DEFAULT_DRIVER = "ODBC Driver 17 for SQL Server"
DEFAULT_REF    = "WELL_REF.well_ref.well_master_gold"
ZERO_UWI = "00000000000000"

FILL_MAP = {                                   # reference col -> header col
    "WELL_NAME": "WELL_NAME", "OPERATOR_NAME": "OPERATOR",
    "FIELD_NAME": "WELL_FIELD", "PROVINCE_STATE": "STATE", "COUNTY": "COUNTY",
    "SURFACE_LATITUDE": "LATITUDE", "SURFACE_LONGITUDE": "LONGITUDE",
}
MATCH_MAP = {                                  # header col -> reference col
    "COUNTY": "COUNTY", "STATE": "PROVINCE_STATE", "OPERATOR": "OPERATOR_NAME",
    "WELL_FIELD": "FIELD_NAME", "TOTAL_DEPTH": "TOTAL_DEPTH", "SPUD_DATE": "SPUD_DATE",
}
REVERSE_MAP = {                                # header col -> reference col (doc -> master)
    "WELL_NAME": "WELL_NAME", "OPERATOR": "OPERATOR_NAME", "WELL_FIELD": "FIELD_NAME",
    "STATE": "PROVINCE_STATE", "COUNTY": "COUNTY",
    "LATITUDE": "SURFACE_LATITUDE", "LONGITUDE": "SURFACE_LONGITUDE",
    "TOTAL_DEPTH": "TOTAL_DEPTH", "SPUD_DATE": "SPUD_DATE",
}
DOC_CONTRIB = "file_catalog.DOC_CONTRIBUTION"  # durable, accumulates across runs


# ── helpers ───────────────────────────────────────────────────────────────────
def sql_conn(a):
    if pyodbc is None:
        sys.exit("pip install pyodbc")
    return pyodbc.connect(
        f"DRIVER={{{a.odbc_driver}}};SERVER={a.server};DATABASE={a.database};"
        "Trusted_Connection=yes;", autocommit=True)


def say(m):
    print(m, flush=True)


def table_cols(cur, fqtn):
    pre = (fqtn.split(".")[0] + ".sys.columns c") if fqtn.count(".") == 2 else "sys.columns c"
    return {r[0].upper() for r in cur.execute(
        f"SELECT c.name FROM {pre} WHERE c.object_id = OBJECT_ID('{fqtn}')").fetchall()}


# ── T-SQL expression builders (normalisation done on the server) ──────────────
def nn_sql(col):
    """NAME_NORM equivalent: tabs/CRs/LFs -> space, collapse runs, UPPER+TRIM.
    Matches the Snowflake UPPER(TRIM(REGEXP_REPLACE(name,'\\s+','')))."""
    x = f"REPLACE(REPLACE(REPLACE({col},CHAR(9),' '),CHAR(13),' '),CHAR(10),' ')"
    for _ in range(4):                          # collapse up to 16 spaces -> 1
        x = f"REPLACE({x},'  ',' ')"
    return f"CAST(UPPER(LTRIM(RTRIM({x}))) AS VARCHAR(510))"  # varchar: keep the gold NAME_NORM index seekable


def u14_sql(col):
    """UWI14 equivalent: drop -_./ and spaces, reject anything non-numeric, then
    pad/truncate to 14. NULL when it can't be a real API key."""
    c = (f"REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM({col})),"
         f"'-',''),' ',''),'.',''),'/',''),'_','')")
    return (f"(CASE WHEN {c} NOT LIKE '%[^0-9]%' AND LEN({c}) >= 10 "
            f"THEN LEFT({c} + REPLICATE('0',14), 14) ELSE NULL END)")


def score_expr(match_pairs, tol):
    terms = []
    for hc, rc in match_pairs:
        if hc == "TOTAL_DEPTH":
            terms.append(
                "CASE WHEN TRY_CONVERT(float,h.[TOTAL_DEPTH]) IS NOT NULL "
                f"AND TRY_CONVERT(float,m.[{rc}]) IS NOT NULL "
                f"AND ABS(TRY_CONVERT(float,h.[TOTAL_DEPTH])-TRY_CONVERT(float,m.[{rc}])) <= {tol} "
                "THEN 2 ELSE 0 END")
        elif hc == "SPUD_DATE":
            terms.append(
                "CASE WHEN TRY_CONVERT(date,h.[SPUD_DATE]) IS NOT NULL "
                f"AND TRY_CONVERT(date,h.[SPUD_DATE]) = TRY_CONVERT(date,m.[{rc}]) "
                "THEN 2 ELSE 0 END")
        else:
            terms.append(
                f"CASE WHEN NULLIF(LTRIM(RTRIM(h.[{hc}])),'') IS NOT NULL "
                f"AND UPPER(LTRIM(RTRIM(h.[{hc}]))) = UPPER(LTRIM(RTRIM(m.[{rc}]))) "
                "THEN 1 ELSE 0 END")
    return " + ".join(terms) if terms else "0"


def blank(col):
    return f"({col} IS NULL OR LTRIM(RTRIM({col})) = '')"


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Enrich catalog headers from the well master (all server-side).")
    p.add_argument("--server", default=DEFAULT_SERVER)
    p.add_argument("--database", default=DEFAULT_DB)
    p.add_argument("--odbc-driver", default=DEFAULT_DRIVER)
    p.add_argument("--ref", default=DEFAULT_REF, help="3-part well master name")
    p.add_argument("--depth-tol", type=float, default=50.0)
    p.add_argument("--no-well", action="store_true")
    p.add_argument("--no-seis", action="store_true")
    p.add_argument("--no-reverse", action="store_true",
                   help="skip reverse-capture of document values the reference is missing")
    p.add_argument("--reverse-report", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--report", default=None)
    a = p.parse_args()
    conn = sql_conn(a)
    enrich(conn, a)


def enrich(conn, a, log=print, progress=None):
    """Core enrichment — callable from the CLI or the app UI.

    `conn`  any DBAPI connection (pyodbc, or sqlalchemy engine.raw_connection()).
    `a`     namespace with the same attributes the CLI args define
            (ref, depth_tol, no_well, no_seis, no_reverse, dry_run, report,
             reverse_report, server, database).
    `log`   receives progress lines (print for CLI, a Streamlit sink for the UI).
    `progress`  optional callable(step, total, label) for a UI progress bar.
    Returns a small summary dict. Commits once at the end on a live run.
    """
    say = log

    # ── per-phase timing + optional progress bar ─────────────────────────────
    # _tick(label) is called at the START of each phase: it closes out the
    # previous phase's wall-clock (logged as [TIME ]) and advances the bar.
    _want_well = not a.no_well
    _want_rev  = _want_well and not a.no_reverse
    _want_seis = not a.no_seis
    _total = (1                              # reflect schema
              + (1 if _want_well else 0)     # pass 0 curate
              + (1 if _want_rev  else 0)     # reverse capture
              + (2 if _want_well else 0)     # pass 1 + pass 2
              + (1 if _want_seis else 0))    # SEIS
    _t0 = time.perf_counter()
    _clk = {"last": _t0, "prev": None, "i": 0}

    def _tick(label):
        now = time.perf_counter()
        if _clk["prev"] is not None:
            say(f"[TIME ] {_clk['prev']}: {now - _clk['last']:.2f}s")
        _clk["last"] = now
        _clk["prev"] = label
        _clk["i"] += 1
        if progress:
            try:
                progress(_clk["i"], _total, label)
            except Exception:
                pass

    def _done():
        now = time.perf_counter()
        if _clk["prev"] is not None:
            say(f"[TIME ] {_clk['prev']}: {now - _clk['last']:.2f}s")
        say(f"[TIME ] total: {now - _t0:.2f}s")
        if progress:
            try:
                progress(_total, _total, "complete")
            except Exception:
                pass

    say(f"[CONNECT] {getattr(a, 'server', '?')} / {getattr(a, 'database', '?')}")
    cur = conn.cursor()
    ref = a.ref

    _tick("reflect schema")
    try:
        ref_cols = table_cols(cur, ref)
    except Exception as e:
        raise RuntimeError(f"Reference {ref} not reachable: {e}")
    whc = table_cols(cur, "file_catalog.FILE_WELL_HEADER")
    shc = table_cols(cur, "file_catalog.FILE_SEIS_HEADER")

    fill_pairs  = [(rc, hc) for rc, hc in FILL_MAP.items() if rc in ref_cols and hc in whc]
    match_pairs = [(hc, rc) for hc, rc in MATCH_MAP.items() if hc in whc and rc in ref_cols]
    say(f"[REF   ] fill from: {', '.join(rc for rc, _ in fill_pairs) or '—'}")
    say(f"[REF   ] disambiguate on: {', '.join(h for h, _ in match_pairs) or 'name only'}")

    audit = []
    rev = []
    nnH = nn_sql("h.WELL_NAME")

    # ── WELL pass 0: curate persisted UWI14 on the header (then 1-2 use it) ──
    has_uwi14 = "UWI14" in whc
    if not a.no_well:
        cur.execute(
            "IF COL_LENGTH('file_catalog.FILE_WELL_HEADER','LAST_ENRICHED_AT') IS NULL "
            "ALTER TABLE file_catalog.FILE_WELL_HEADER ADD LAST_ENRICHED_AT datetime2 NULL")
        _tick("pass 0 — curate UWI14")
        say("[WELL  ] pass 0 — curating UWI14 (persisted key)…")
        cur.execute(f"""
            SELECT
              SUM(CASE WHEN {u14_sql('UWI')} IS NOT NULL THEN 1 ELSE 0 END),
              SUM(CASE WHEN {u14_sql('UWI')} IS NULL
                        AND NULLIF(LTRIM(RTRIM(UWI)),'') IS NOT NULL THEN 1 ELSE 0 END)
            FROM file_catalog.FILE_WELL_HEADER""")
        _ok, _flag = cur.fetchone()
        say(f"[WELL  ] UWI14 valid: {(_ok or 0):,}   "
            f"flagged (UWI present, not an API): {(_flag or 0):,}")
        if not a.dry_run:
            if not has_uwi14:
                cur.execute("ALTER TABLE file_catalog.FILE_WELL_HEADER ADD UWI14 CHAR(14) NULL")
                say("[WELL  ] added column UWI14")
            cur.execute(f"UPDATE file_catalog.FILE_WELL_HEADER SET UWI14 = {u14_sql('UWI')}")
            cur.execute(
                "IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_FWH_UWI14' "
                "AND object_id = OBJECT_ID('file_catalog.FILE_WELL_HEADER')) "
                "CREATE INDEX IX_FWH_UWI14 ON file_catalog.FILE_WELL_HEADER(UWI14)")
            has_uwi14 = True
            say("[WELL  ] UWI14 populated + indexed")

        # passes 1-2 read the stored column when present, else compute inline
        if has_uwi14:
            u14H    = "h.UWI14"
            u14_src = "SELECT UWI14 FROM file_catalog.FILE_WELL_HEADER WHERE UWI14 IS NOT NULL"
        else:
            u14H    = u14_sql("h.UWI")
            u14_src = (f"SELECT {u14_sql('UWI')} FROM file_catalog.FILE_WELL_HEADER "
                       f"WHERE UWI IS NOT NULL")

        # ── reverse-capture: document values the reference is MISSING ────────
        # Runs BEFORE pass 1 so the gate uses the document's own extracted UWI
        # (raw h.UWI), never a name-resolved key. Read-only; the live table
        # write only records gaps — it never touches the reference itself.
        if not a.no_reverse:
            rev_pairs = [(hc, rc) for hc, rc in REVERSE_MAP.items()
                         if hc in whc and rc in ref_cols]
            if rev_pairs:
                _tick("reverse capture")
                say("[WELL  ] reverse-capture — document values absent from the reference…")
                dk = u14_sql("h.UWI")                       # document key, raw UWI
                # Filter the master with the persisted (indexed) UWI14 column via
                # u14_src — a sargable seek instead of a 4M-row scan over a
                # recomputed expression. At this point (after pass 0, before the
                # name resolution in pass 1) the persisted UWI14 still equals the
                # document's own raw-UWI key, so the reverse-capture gate is
                # unchanged; only the master-side filter gets faster.
                doc_keys = u14_src
                rc_set = sorted({rc for _, rc in rev_pairs})
                has_cols = ", ".join(
                    f"MAX(CASE WHEN NULLIF(LTRIM(RTRIM([{rc}])),'') IS NOT NULL "
                    f"THEN 1 ELSE 0 END) AS has_{rc}" for rc in rc_set)

                # Materialise the reference summary ONCE. As an inline CTE it was
                # re-evaluated per UNION ALL arm — one 4M-row master scan each;
                # in a temp table the master is scanned a single time.
                cur.execute("IF OBJECT_ID('tempdb..#refg') IS NOT NULL DROP TABLE #refg")
                cur.execute(
                    f"SELECT UWI14, {has_cols} INTO #refg FROM {ref} "
                    f"WHERE UWI_SUSPECT = 0 AND UWI14 <> '{ZERO_UWI}' "
                    f"AND UWI14 IN ({doc_keys}) GROUP BY UWI14")
                cur.execute("CREATE INDEX IX_refg ON #refg(UWI14)")

                def _valid(hc):
                    if hc in ("TOTAL_DEPTH", "LATITUDE", "LONGITUDE"):
                        return f" AND TRY_CONVERT(float, h.[{hc}]) IS NOT NULL"
                    if hc == "SPUD_DATE":
                        return f" AND TRY_CONVERT(date, h.[{hc}]) IS NOT NULL"
                    return ""

                arms = []
                for hc, rc in rev_pairs:
                    dv = f"LTRIM(RTRIM(CONVERT(NVARCHAR(400), h.[{hc}])))"
                    arms.append(
                        f"SELECT CAST(h.WELL_HEADER_ID AS NVARCHAR(64)) AS WELL_HEADER_ID, "
                        f"CAST(h.INVENTORY_ID AS NVARCHAR(64)) AS INVENTORY_ID, "
                        f"g.FILE_PATH AS SOURCE_PATH, {dk} AS UWI14, "
                        f"'{rc}' AS FIELD, {dv} AS DOC_VALUE "
                        f"FROM file_catalog.FILE_WELL_HEADER h "
                        f"JOIN file_catalog.GLOBAL_FILE_CATALOG g ON g.INVENTORY_ID = h.INVENTORY_ID "
                        f"JOIN #refg r ON r.UWI14 = {dk} "
                        f"WHERE r.has_{rc} = 0 AND NULLIF({dv},'') IS NOT NULL{_valid(hc)}")

                # Stage the gap candidates once so we can both audit and insert
                # without re-running the (now temp-backed) arms.
                cur.execute("IF OBJECT_ID('tempdb..#gaps') IS NOT NULL DROP TABLE #gaps")
                cur.execute("SELECT * INTO #gaps FROM ("
                            + " UNION ALL ".join(arms) + ") q")

                for whid, inv, src, u14, fld, val in cur.execute(
                        "SELECT WELL_HEADER_ID, INVENTORY_ID, SOURCE_PATH, "
                        "UWI14, FIELD, DOC_VALUE FROM #gaps").fetchall():
                    rev.append({"uwi14": u14, "field": fld, "doc_value": val,
                                "source_path": src, "inventory_id": inv,
                                "well_header_id": whid, "status": "gap"})
                say(f"[WELL  ] reverse contributions (ref gaps documents can fill): {len(rev):,}")

                if rev and not a.dry_run:
                    cur.execute(
                        f"IF OBJECT_ID('{DOC_CONTRIB}') IS NULL CREATE TABLE {DOC_CONTRIB} ("
                        " CONTRIB_ID BIGINT IDENTITY(1,1) PRIMARY KEY,"
                        " UWI14 CHAR(14) NOT NULL, FIELD VARCHAR(40) NOT NULL,"
                        " DOC_VALUE NVARCHAR(400) NULL, SOURCE_PATH NVARCHAR(1024) NULL,"
                        " INVENTORY_ID NVARCHAR(64) NULL, WELL_HEADER_ID NVARCHAR(64) NULL,"
                        " STATUS VARCHAR(12) NOT NULL CONSTRAINT DF_DC_STATUS DEFAULT 'gap',"
                        " CAPTURED_AT DATETIME2 NOT NULL CONSTRAINT DF_DC_CAP DEFAULT SYSUTCDATETIME(),"
                        " PUSHED BIT NOT NULL CONSTRAINT DF_DC_PUSH DEFAULT 0)")
                    # one set-based insert: dedup within this batch (GROUP BY the
                    # contribution key) and against rows already stored.
                    cur.execute(
                        f"INSERT INTO {DOC_CONTRIB} "
                        "(UWI14, FIELD, DOC_VALUE, SOURCE_PATH, INVENTORY_ID, WELL_HEADER_ID, STATUS) "
                        "SELECT s.UWI14, s.FIELD, s.DOC_VALUE, s.SOURCE_PATH, "
                        "s.INVENTORY_ID, s.WELL_HEADER_ID, 'gap' "
                        "FROM (SELECT UWI14, FIELD, DOC_VALUE, SOURCE_PATH, "
                        "             MIN(INVENTORY_ID) AS INVENTORY_ID, "
                        "             MIN(WELL_HEADER_ID) AS WELL_HEADER_ID "
                        "      FROM #gaps "
                        "      GROUP BY UWI14, FIELD, DOC_VALUE, SOURCE_PATH) s "
                        f"WHERE NOT EXISTS (SELECT 1 FROM {DOC_CONTRIB} d "
                        "WHERE d.UWI14 = s.UWI14 AND d.FIELD = s.FIELD "
                        "AND ISNULL(d.DOC_VALUE,'') = ISNULL(s.DOC_VALUE,'') "
                        "AND ISNULL(d.SOURCE_PATH,'') = ISNULL(s.SOURCE_PATH,''))")
                    nnew = cur.rowcount or 0
                    say(f"[WELL  ] {DOC_CONTRIB}: +{nnew:,} new (deduped against existing)")


    # ── WELL pass 1: resolve a missing UWI by name (+ attribute tie-break) ───
    if not a.no_well:
        _tick("pass 1 — resolve missing UWI")
        say("[WELL  ] pass 1 — resolving missing UWIs (server-side join)…")

        # Materialize the name→reference matches ONCE. The previous version put
        # the WELL_MASTER join in a CTE (`scored`) that `agg`, `pk` and the final
        # SELECT each referenced — and a multiply-referenced CTE over a 2.5M-row
        # CROSS-DATABASE table is re-evaluated per reference, re-scanning
        # WELL_MASTER several times (and again for the UPDATE). Pulling it into
        # #scored forces a single pass; every aggregation below is then local.
        # Use the NAME_NORM index hint ONLY if that index exists on the ref
        # table — otherwise SQL Server errors (308) instead of ignoring it.
        # Missing index = slower join, never a failed stage.
        _ixhint = ""
        try:
            cur.execute("SELECT 1 FROM sys.indexes WHERE name='IX_WM_NAME_NORM' AND object_id=OBJECT_ID(?)", ref)
            if cur.fetchone():
                _ixhint = " WITH (INDEX(IX_WM_NAME_NORM))"
        except Exception:
            _ixhint = ""
        cur.execute("IF OBJECT_ID('tempdb..#scored') IS NOT NULL DROP TABLE #scored")
        # Cheap LOCAL pre-check: how many headers still have a blank UWI to
        # resolve? Pass 0 curates UWI14 for most, so this is usually 0 — and
        # when it is, skip the 3.9M-row cross-DB gold join entirely (was ~6s of
        # pure waste). Build an empty #scored so the rest of pass 1 no-ops.
        _need1 = cur.execute(
            f"SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER h "
            f"WHERE {blank('h.UWI')} AND {nnH} <> ''").fetchone()[0]
        if _need1:
            cur.execute(f"""
                SELECT h.WELL_HEADER_ID, m.UWI14,
                       ({score_expr(match_pairs, a.depth_tol)}) AS score
                INTO #scored
                FROM file_catalog.FILE_WELL_HEADER h
                INNER LOOP JOIN {ref} m{_ixhint}
                  ON m.NAME_NORM = {nnH} AND m.UWI_SUSPECT = 0
                 AND m.UWI14 IS NOT NULL AND m.UWI14 <> '{ZERO_UWI}'
                WHERE {blank('h.UWI')} AND {nnH} <> ''""")
        else:
            say("[WELL  ] pass 1 — 0 blank UWIs; skipped the 3.9M-row gold join")
            cur.execute("SELECT TOP 0 h.WELL_HEADER_ID, "
                        "CAST(NULL AS CHAR(14)) AS UWI14, CAST(0 AS INT) AS score "
                        "INTO #scored FROM file_catalog.FILE_WELL_HEADER h WHERE 1=0")
        cur.execute("CREATE INDEX IX_scored ON #scored(WELL_HEADER_ID)")

        # one row per header: distinct-UWI count, best score, and how many
        # distinct UWIs tie at that best score — all against the local temp
        cur.execute("IF OBJECT_ID('tempdb..#pick') IS NOT NULL DROP TABLE #pick")
        cur.execute("""
            WITH agg AS (
                SELECT WELL_HEADER_ID, COUNT(DISTINCT UWI14) AS uwis,
                       MAX(score) AS topscore
                FROM #scored GROUP BY WELL_HEADER_ID),
            pk AS (
                SELECT s.WELL_HEADER_ID, COUNT(DISTINCT s.UWI14) AS top_uwis,
                       MIN(s.UWI14) AS uwi14
                FROM #scored s
                JOIN agg a ON a.WELL_HEADER_ID = s.WELL_HEADER_ID
                          AND s.score = a.topscore
                GROUP BY s.WELL_HEADER_ID)
            SELECT a.WELL_HEADER_ID, a.uwis, a.topscore, pk.top_uwis, pk.uwi14
            INTO #pick
            FROM agg a JOIN pk ON pk.WELL_HEADER_ID = a.WELL_HEADER_ID""")
        where_ok = "p.uwis = 1 OR (p.top_uwis = 1 AND p.topscore >= 1)"

        n = 0
        for hid, inv, u14, wn, old, top in cur.execute(f"""
            SELECT p.WELL_HEADER_ID, h.INVENTORY_ID, p.uwi14, h.WELL_NAME,
                   h.UWI, p.topscore
            FROM #pick p
            JOIN file_catalog.FILE_WELL_HEADER h
              ON h.WELL_HEADER_ID = p.WELL_HEADER_ID
            WHERE {where_ok}""").fetchall():
            n += 1
            audit.append({"table": "WELL", "inventory_id": inv, "action": "set-uwi",
                          "column": "UWI", "old": old or "", "new": u14,
                          "basis": f"name+score{int(top or 0)}"})
        say(f"[WELL  ] resolvable UWIs: {n:,}")
        if n and not a.dry_run:
            cur.execute(f"""
                UPDATE h SET h.UWI = p.uwi14, h.UWI14 = p.uwi14
                FROM file_catalog.FILE_WELL_HEADER h
                JOIN #pick p ON p.WELL_HEADER_ID = h.WELL_HEADER_ID
                WHERE ({where_ok}) AND {blank('h.UWI')}""")
            say(f"[WELL  ] wrote {n:,} UWI(s)")
        cur.execute("IF OBJECT_ID('tempdb..#scored') IS NOT NULL DROP TABLE #scored")
        cur.execute("IF OBJECT_ID('tempdb..#pick') IS NOT NULL DROP TABLE #pick")

        # ── WELL pass 2: fill blank attributes by UWI ────────────────────────
        _tick("pass 2 — fill blank attributes")
        if fill_pairs:
            agg_cols = ", ".join(
                f"CASE WHEN COUNT(DISTINCT [{rc}])=1 THEN MAX([{rc}]) END AS [{rc}]"
                for rc, _ in fill_pairs)
            _p2_keys = ("SELECT UWI14 FROM file_catalog.FILE_WELL_HEADER "
                        "WHERE UWI14 IS NOT NULL AND LAST_ENRICHED_AT IS NULL")
            refagg = f"""SELECT UWI14, {agg_cols} FROM {ref}
                WHERE UWI_SUSPECT = 0 AND UWI14 <> '{ZERO_UWI}'
                  AND UWI14 IN ({_p2_keys})
                GROUP BY UWI14"""
            any_blank = " OR ".join(blank(f"h.[{hc}]") for _, hc in fill_pairs)
            sel = ", ".join([f"h.[{hc}] AS cur_{hc}" for _, hc in fill_pairs]
                            + [f"r.[{rc}] AS ref_{rc}" for rc, _ in fill_pairs])
            say("[WELL  ] pass 2 — filling blank attributes…")
            cur.execute(f""";WITH r AS ({refagg})
                SELECT h.WELL_HEADER_ID, h.INVENTORY_ID, {sel}
                FROM file_catalog.FILE_WELL_HEADER h
                JOIN r ON r.UWI14 = {u14H}
                WHERE ({any_blank}) AND h.LAST_ENRICHED_AT IS NULL""")
            cols = [d[0] for d in cur.description]
            nf = 0
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                for rc, hc in fill_pairs:
                    cv, rv = d.get(f"cur_{hc}"), d.get(f"ref_{rc}")
                    if (cv is None or str(cv).strip() == "") and rv not in (None, "") \
                            and str(rv).strip() != "":
                        nf += 1
                        audit.append({"table": "WELL", "inventory_id": d.get("INVENTORY_ID"),
                                      "action": "fill", "column": hc, "old": "",
                                      "new": str(rv), "basis": "uwi"})
            say(f"[WELL  ] blank-attr fills: {nf:,}")
            if nf and not a.dry_run:
                sets = ", ".join(
                    f"h.[{hc}] = CASE WHEN {blank(f'h.[{hc}]')} THEN r.[{rc}] ELSE h.[{hc}] END"
                    for rc, hc in fill_pairs)
                cur.execute(f""";WITH r AS ({refagg})
                    UPDATE h SET {sets}
                    FROM file_catalog.FILE_WELL_HEADER h
                    JOIN r ON r.UWI14 = {u14H}
                    WHERE ({any_blank}) AND h.LAST_ENRICHED_AT IS NULL""")
                say("[WELL  ] applied fills")

        # stamp rows we just enriched so the next run skips them (incremental)
        if not a.dry_run:
            cur.execute(
                "UPDATE file_catalog.FILE_WELL_HEADER SET LAST_ENRICHED_AT = SYSUTCDATETIME() "
                "WHERE LAST_ENRICHED_AT IS NULL AND UWI14 IS NOT NULL")

    # ── SEIS pass: survey name from the file name (also server-side) ─────────
    if not a.no_seis and "SURVEY_NAME" in shc:
        set_col = "SEIS_SET_TYPE" if "SEIS_SET_TYPE" in shc else None
        pn   = "REPLACE(g.FILE_PATH,'/','\\')"
        base = f"RIGHT({pn}, CHARINDEX('\\', REVERSE({pn}) + '\\') - 1)"
        stem = (f"CASE WHEN {base} LIKE '%.%' "
                f"THEN LEFT({base}, LEN({base}) - CHARINDEX('.', REVERSE({base}))) ELSE {base} END")
        sv = f"REPLACE(REPLACE(REPLACE({stem},'_',' '),'-',' '),'.',' ')"
        for _ in range(4):
            sv = f"REPLACE({sv},'  ',' ')"
        survey = f"NULLIF(LTRIM(RTRIM({sv})),'')"
        dim = f"CASE WHEN {base} LIKE '%3D%' THEN '3D' WHEN {base} LIKE '%2D%' THEN '2D' END"

        _tick("SEIS — survey from file name")
        say("[SEIS  ] survey-from-name (server-side)…")
        cur.execute(f"""
            SELECT sh.SEIS_HEADER_ID, sh.INVENTORY_ID, {survey} AS survey, {dim} AS dim
            FROM file_catalog.FILE_SEIS_HEADER sh
            JOIN file_catalog.GLOBAL_FILE_CATALOG g ON g.INVENTORY_ID = sh.INVENTORY_ID
            WHERE {blank('sh.SURVEY_NAME')} AND {survey} IS NOT NULL""")
        ns = 0
        for sid, inv, sv_v, dim_v in cur.fetchall():
            ns += 1
            audit.append({"table": "SEIS", "inventory_id": inv, "action": "set-survey",
                          "column": "SURVEY_NAME", "old": "", "new": sv_v, "basis": "filename"})
        say(f"[SEIS  ] survey-from-name: {ns:,}")
        if ns and not a.dry_run:
            setty = (f", sh.SEIS_SET_TYPE = CASE WHEN {blank('sh.SEIS_SET_TYPE')} "
                     f"AND {dim} IS NOT NULL THEN {dim} ELSE sh.SEIS_SET_TYPE END") if set_col else ""
            cur.execute(f"""
                UPDATE sh SET sh.SURVEY_NAME = {survey}{setty}
                FROM file_catalog.FILE_SEIS_HEADER sh
                JOIN file_catalog.GLOBAL_FILE_CATALOG g ON g.INVENTORY_ID = sh.INVENTORY_ID
                WHERE {blank('sh.SURVEY_NAME')} AND {survey} IS NOT NULL""")
            say(f"[SEIS  ] applied {ns:,}")

    # ── audit + summary ──────────────────────────────────────────────────────
    _done()
    rpt = a.report or f"enrich_report_{datetime.now():%Y%m%d_%H%M%S}.csv"
    try:
        with open(rpt, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=[
                "table", "inventory_id", "action", "column", "old", "new", "basis"])
            w.writeheader()
            w.writerows(audit)
        rpt_note = os.path.abspath(rpt)
    except Exception as e:
        rpt_note = f"(report not written: {e})"

    by = defaultdict(int)
    for r in audit:
        by[(r["table"], r["action"])] += 1
    say("\n──────── summary ────────")
    for (tbl, act), nn in sorted(by.items()):
        say(f"  {tbl:5} {act:12} {nn:,}")
    say(f"\n{'(dry run — nothing written) ' if a.dry_run else ''}Report: {rpt_note}")

    # ── reverse-contribution audit (document -> reference gaps) ───────────────
    if not a.no_reverse:
        rev_by = defaultdict(int)
        for r in rev:
            rev_by[r["field"]] += 1
        rrpt = a.reverse_report or f"reverse_contrib_{datetime.now():%Y%m%d_%H%M%S}.csv"
        try:
            with open(rrpt, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=[
                    "uwi14", "field", "doc_value", "source_path",
                    "inventory_id", "well_header_id", "status"])
                w.writeheader()
                w.writerows(rev)
            rrpt_note = os.path.abspath(rrpt)
        except Exception as e:
            rrpt_note = f"(reverse report not written: {e})"
        say("\n──── reverse contributions (by field) ────")
        for fld, nn in sorted(rev_by.items()):
            say(f"  {fld:18} {nn:,}")
        sink = "(dry run — staged to CSV only) " if a.dry_run else f"{DOC_CONTRIB} + "
        say(f"{sink}{rrpt_note}  ({len(rev):,} rows)")

    if not getattr(a, "dry_run", False):
        try:
            conn.commit()
        except Exception:
            pass
    return {"forward": dict(by), "reverse": len(rev), "report": rpt_note}


if __name__ == "__main__":
    main()
