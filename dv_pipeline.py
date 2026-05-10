"""
dv_pipeline.py
==============
DataView v3 — Generalized Multi-Table Loading Engine

Handles the full pipeline from uploaded DataFrame to target table(s):

  Stage 1  detect_targets()      — ML scores source cols against all 46 tables,
                                   returns ranked (table, col, score) groups
  Stage 2  build_stg_table()     — DROP/CREATE dataview.dv_stg_{target} with
                                   _stg_row_id IDENTITY + mapped columns (all NVARCHAR)
  Stage 3  bulk_insert_stg()     — BULK INSERT via temp TSV into staging table
  Stage 4  normalize_stg()       — server-side TRIM/UPPER/ISO-date via normalize.py
  Stage 5  validate_stg()        — UWI format, lat/lon, dates, nulls → ValidationReport
  Stage 6  apply_code_maps()     — UPDATE staging: well_type, well_status, etc.
  Stage 7  seed_entities()       — INSERT missing BAs, fields, etc.
  Stage 8  promote_stg()         — INSERT INTO target SELECT FROM stg WHERE NOT bad
                                   bad rows → rejection CSV

Schema metadata loaded from:
  schema_registry/dataview_schema_domain.json   — 879 column entries, 46 tables
  schema_registry/dataview_fk_catalog.json      — FK graph, PKs, col types
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import text

# ── Schema registry paths ─────────────────────────────────────────────
_REGISTRY = Path("schema_registry")
_DOMAIN_FILE = _REGISTRY / "dataview_schema_domain.json"
_FK_FILE     = _REGISTRY / "dataview_fk_catalog.json"

# ── Audit columns auto-stamped on every insert ────────────────────────
_AUDIT_COLS = {
    "active_ind", "row_created_by", "row_created_date",
    "row_changed_by", "row_changed_date", "source",
}

# ── Tables excluded from target selection ─────────────────────────────
_EXCLUDED_TABLES = {
    "dv_r_source", "dv_r_well_type", "dv_r_well_status", "dv_r_uom",
    "dv_column_map", "dv_load_batch", "dv_data_quality",
}

# ── Training corpus path ──────────────────────────────────────────────
_CORPUS_FILE = _REGISTRY / "dv_training_corpus.json"


def _load_corpus() -> dict[str, list[dict]]:
    """
    Load training corpus as {source_col_upper: [entry, ...]} lookup.
    Returns empty dict if corpus file not found.
    """
    if not _CORPUS_FILE.exists():
        return {}
    with open(_CORPUS_FILE, encoding="utf-8") as f:
        corpus = json.load(f)
    lookup: dict[str, list[dict]] = {}
    for entry in corpus.get("entries", []):
        key = entry["source_col"].upper()
        lookup.setdefault(key, []).append(entry)
    return lookup


def save_to_corpus(
    mappings: list[dict],
    source_agency: str,
    source_file: str,
) -> int:
    """
    Add confirmed mappings to the training corpus.
    Skips entries already in corpus (same source_col + target_col).
    Returns number of new entries added.
    """
    existing = []
    if _CORPUS_FILE.exists():
        with open(_CORPUS_FILE, encoding="utf-8") as f:
            corpus = json.load(f)
        existing = corpus.get("entries", [])
    else:
        corpus = {
            "version": "1.0",
            "created": datetime.utcnow().isoformat(),
            "description": "DataView v3 ML training corpus.",
            "uwi_standard": "14-digit no-dash",
            "entries": [],
        }

    existing_keys = {
        (e["source_col"].upper(), e.get("target_col", ""), e.get("target_table", ""))
        for e in existing
    }

    added = 0
    for m in mappings:
        key = (
            m["src"].upper(),
            m.get("target") or "",
            m.get("target_table", "dv_well"),
        )
        if key not in existing_keys:
            existing.append({
                "source_col":    m["src"],
                "target_table":  m.get("target_table", "dv_well") if m.get("target") else None,
                "target_col":    m.get("target"),
                "confidence":    1.0,
                "source_agency": source_agency,
                "source_file":   source_file,
                "note":          "auto-saved from confirmed fingerprint",
            })
            existing_keys.add(key)
            added += 1

    corpus["entries"] = existing
    _CORPUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_CORPUS_FILE, "w", encoding="utf-8") as f:
        json.dump(corpus, f, indent=2)
    return added

# ── Target auto-detection hints ───────────────────────────────────────
# (filename_pattern, column_hints, target_table)
_FILE_HINTS = [
    (r"well",      ["uwi", "api", "kid", "well_name"],     "dv_well"),
    (r"seis",      ["line_name", "cdp", "fold", "seis"],   "dv_seis_set"),
    (r"survey",    ["md", "incl", "azim", "tvd"],          "dv_well_dir_srvy_sta"),
    (r"dir.?srvy", ["md", "incl", "azim", "tvd"],          "dv_well_dir_srvy_sta"),
    (r"prod",      ["prod_date", "oil_vol", "gas_vol"],     "dv_prod_volume"),
    (r"perf",      ["top_depth", "bot_depth", "perforat"],  "dv_well_perforation"),
    (r"tops",      ["top_md", "formation", "strat"],        "dv_well_formation_top"),
    (r"log",       ["curve", "las", "depth_from"],          "dv_well_log"),
    (r"core",      ["core_num", "core_top", "core_base"],   "dv_well_core"),
    (r"dst",       ["dst", "shut_in", "flow_period"],       "dv_well_dst"),
    (r"stim",      ["stim", "frac", "treatment"],           "dv_well_stimulation"),
    (r"pressure",  ["pressure", "reservoir_pressure"],      "dv_well_pressure"),
    (r"shows",     ["show", "fluorescence", "cut"],         "dv_well_shows"),
]


# =============================================================================
# SCHEMA CACHE — loaded once per session
# =============================================================================

class _SchemaCache:
    _domain: list[dict] | None = None
    _fk: dict | None = None

    @classmethod
    def domain(cls) -> list[dict]:
        if cls._domain is None:
            with open(_DOMAIN_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            cls._domain = raw["ppdm_39_schema_domain"]
        return cls._domain

    @classmethod
    def fk(cls) -> dict:
        if cls._fk is None:
            with open(_FK_FILE, encoding="utf-8") as f:
                cls._fk = json.load(f)
        return cls._fk

    @classmethod
    def table_cols(cls, table: str) -> dict[str, str]:
        """Return {col_name_upper: data_type} for a table."""
        return cls.fk()["table_cols"].get(table.upper(), {})

    @classmethod
    def table_pk(cls, table: str) -> list[str]:
        """Return PK column names (upper) for a table."""
        return cls.fk()["table_pk"].get(table.upper(), [])

    @classmethod
    def table_fks(cls, table: str) -> list[dict]:
        """Return FK constraints for a table."""
        return cls.fk()["fk_constraints"].get(table.upper(), [])

    @classmethod
    def loadable_tables(cls) -> list[str]:
        """Return sorted list of tables available as load targets."""
        domain = cls.domain()
        tables = sorted({
            e["table_name"] for e in domain
            if e["table_name"] not in _EXCLUDED_TABLES
            and not e["table_name"].startswith("dv_r_")
            and not e["table_name"].startswith("dv_stg")
        })
        return tables

    @classmethod
    def domain_for_table(cls, table: str) -> list[dict]:
        """Return all domain entries for a given table."""
        return [e for e in cls.domain() if e["table_name"] == table]


# =============================================================================
# STAGE 1 — TARGET DETECTION
# =============================================================================

@dataclass
class ColumnMatch:
    src_col:    str
    tgt_table:  str
    tgt_col:    str
    score:      float
    method:     str   # "exact" | "keyword" | "embed" | "hint"


@dataclass
class TableGroup:
    table:      str
    matches:    list[ColumnMatch]
    confidence: float   # mean score of matched columns

    @property
    def col_count(self) -> int:
        return len(self.matches)


def _normalise(s: str) -> str:
    return re.sub(r"[^a-z0-9]", " ", s.lower()).strip()


def _token_overlap(a: str, b: str) -> float:
    ta = set(_normalise(a).split())
    tb = set(_normalise(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _keyword_score(src: str, tgt_col: str) -> float:
    src_n  = _normalise(src)
    tgt_n  = _normalise(tgt_col)
    if src_n == tgt_n:
        return 1.0
    if tgt_n in src_n or src_n in tgt_n:
        return 0.85
    return _token_overlap(src_n, tgt_n)


def detect_targets(
    src_cols: list[str],
    filename: str = "",
    use_embeddings: bool = False,
    min_score: float = 0.40,
    top_n_tables: int = 5,
) -> list[TableGroup]:
    """
    Score each source column against every column in every target table.
    Returns a list of TableGroup sorted by confidence desc.

    Each TableGroup contains the best-matching target column per source column
    for that table, where score >= min_score.
    """
    domain = _SchemaCache.domain()

    # Build lookup: {table: [(col_name, data_type)]}
    table_cols: dict[str, list[tuple[str, str]]] = {}
    for e in domain:
        tbl = e["table_name"]
        if tbl in _EXCLUDED_TABLES or tbl.startswith("dv_r_"):
            continue
        table_cols.setdefault(tbl, []).append(
            (e["column_name"], e["data_type"])
        )

    # ── Tier 0: Fingerprint check (exact column set match) ───────────
    # (Handled externally by the importer UI — dv_pipeline focuses on col scoring)

    # ── Tier 1: Training corpus lookup ───────────────────────────────
    corpus = _load_corpus()
    corpus_hits: dict[str, ColumnMatch] = {}  # src_col → ColumnMatch
    corpus_table_votes: dict[str, int] = {}   # table → vote count

    for src in src_cols:
        entries = corpus.get(src.upper(), [])
        for entry in entries:
            tgt_tbl = entry.get("target_table")
            tgt_col = entry.get("target_col")
            if tgt_tbl and tgt_col:
                corpus_hits[src] = ColumnMatch(
                    src_col=src, tgt_table=tgt_tbl,
                    tgt_col=tgt_col, score=1.0, method="corpus"
                )
                corpus_table_votes[tgt_tbl] = (
                    corpus_table_votes.get(tgt_tbl, 0) + 1)
                break  # first corpus hit wins

    # Primary table from corpus votes
    corpus_primary = (max(corpus_table_votes, key=corpus_table_votes.get)
                      if corpus_table_votes else None)

    # ── Tier 2: ML matching ───────────────────────────────────────────
    # Optional: load sentence-transformers
    model = None
    if use_embeddings:
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("all-MiniLM-L6-v2")
        except ImportError:
            pass

    # File-level hint → boost scores for suggested table
    hint_table = _file_hint(filename, src_cols) or corpus_primary

    # Score every (src_col, table, tgt_col) triple
    # best match per (src_col, table)
    results: dict[str, list[ColumnMatch]] = {}  # table → matches

    for src in src_cols:
        # If corpus has a hit for this col, inject it at score=1.0
        # and skip ML scoring for this col in the corpus table
        if src in corpus_hits:
            hit = corpus_hits[src]
            results.setdefault(hit.tgt_table, []).append(hit)

        best_by_table: dict[str, ColumnMatch] = {}
        # Track which tables already have a corpus entry for this src col
        _corpus_covered = {corpus_hits[src].tgt_table} if src in corpus_hits else set()

        for tbl, cols in table_cols.items():
            best_score = 0.0
            best_col   = None

            for tgt_col, dtype in cols:
                if tgt_col.lower() in _AUDIT_COLS:
                    continue
                ks = _keyword_score(src, tgt_col)

                if model:
                    import numpy as np
                    src_text = _normalise(src).replace("_", " ")
                    tgt_text = _normalise(tgt_col).replace("_", " ")
                    emb = model.encode([src_text, tgt_text], convert_to_numpy=True)
                    es = float(np.dot(emb[0], emb[1]) /
                               (np.linalg.norm(emb[0]) * np.linalg.norm(emb[1]) + 1e-9))
                    score = max(ks, es)
                    method = "embed" if es >= ks else "keyword"
                else:
                    score  = ks
                    method = "keyword"

                # Boost hint table
                if tbl == hint_table:
                    score = min(1.0, score * 1.15)
                    method = "hint+" + method

                if score > best_score:
                    best_score = score
                    best_col   = (tgt_col, method)

            if best_score >= min_score and best_col:
                best_by_table[tbl] = ColumnMatch(
                    src_col=src, tgt_table=tbl,
                    tgt_col=best_col[0], score=round(best_score, 3),
                    method=best_col[1],
                )

        # Add best ML match per table — skip if corpus already covers this src+table
        for tbl, match in best_by_table.items():
            if tbl not in _corpus_covered:
                results.setdefault(tbl, []).append(match)

    # Build TableGroups — only tables with ≥2 matched columns
    groups = []
    for tbl, matches in results.items():
        if len(matches) < 2:
            continue
        conf = sum(m.score for m in matches) / len(matches)
        groups.append(TableGroup(table=tbl, matches=matches,
                                 confidence=round(conf, 3)))

    # Merge corpus-only hits into groups (cols that scored below min_score
    # but have corpus matches should still appear in the primary table group)
    for tbl, matches in results.items():
        # Replace any existing group's matches with corpus hits where available
        for g in groups:
            if g.table == tbl:
                existing_srcs = {m.src_col for m in g.matches}
                for m in matches:
                    if m.method == "corpus" and m.src_col not in existing_srcs:
                        g.matches.append(m)
                        existing_srcs.add(m.src_col)
                g.confidence = round(
                    sum(m.score for m in g.matches) / len(g.matches), 3)
                break

    groups.sort(key=lambda g: (g.confidence * g.col_count), reverse=True)
    return groups[:top_n_tables]


def _file_hint(filename: str, src_cols: list[str]) -> str | None:
    """Return suggested primary target table from filename + column patterns."""
    fn = filename.lower()
    col_str = " ".join(c.lower() for c in src_cols)
    for pattern, col_hints, table in _FILE_HINTS:
        if re.search(pattern, fn):
            return table
        if sum(1 for h in col_hints if h in col_str) >= 2:
            return table
    return None



# =============================================================================
# UWI NORMALIZATION — 14-digit no-dash canonical format
# =============================================================================
# Standard: state(2) + county(3) + well(5) + sidetrack(2) + event(2) = 14 digits
# No dashes, no prefix, right-padded with zeros where needed.

def normalize_uwi(raw: str | None) -> str | None:
    """
    Normalize any US API/UWI variant to 14-digit no-dash format.

    Handles:
      10-digit  4250120130          → 42501201300000
      12-digit  425012013000        → 42501201300000
      14-digit  42501201300000      → 42501201300000  (canonical)
      15-digit  151232013000000     → 151232013000000 (KGS Kansas — kept as-is)
      16-digit  4250120130000000    → 42501201300000  (truncate to 14)
      dashed    42-501-20130-00-00  → 42501201300000
      prefixed  US42501201300000    → 42501201300000
      KGS KID   1234567             → None (reject — not an API number)

    Returns None if the value cannot be normalized to a valid API number.
    """
    if raw is None:
        return None
    import re as _re

    # Strip non-numeric characters (dashes, spaces, dots, prefix letters)
    digits = _re.sub(r"[^0-9]", "", str(raw).strip())

    if not digits:
        return None

    n = len(digits)

    if n == 10:
        return digits.ljust(14, "0")        # pad sidetrack + event
    elif n == 12:
        return digits.ljust(14, "0")        # pad event
    elif n == 14:
        return digits                        # canonical — no change
    elif n == 15:
        # KGS Kansas: state code 15 is already 2 digits — keep as-is
        # but check if it starts with a spurious leading zero from a 14-digit
        # padded to 15 by a "0" prefix (e.g. "042501201300000")
        if digits[0] == "0" and digits[1:3] in ("42", "15", "38", "49"):
            return digits[1:]               # strip leading zero → 14 digits
        return digits                        # genuine 15-digit (some agencies)
    elif n == 16:
        return digits[:14]                   # truncate extra codes
    else:
        return None                          # too short (<10) or too long (>16)


def uwi_is_valid(uwi: str | None) -> bool:
    """Return True if uwi is a valid normalized 14 or 15-digit API number."""
    if not uwi:
        return False
    import re as _re
    return bool(_re.match(r"^\d{14,15}$", uwi))


def normalize_uwi_series(series: "pd.Series") -> "pd.Series":
    """Vectorized UWI normalization for a pandas Series."""
    return series.apply(normalize_uwi)

# =============================================================================
# STAGE 2 — STAGING TABLE DDL
# =============================================================================

def build_stg_table(
    engine,
    target_table: str,
    mapped_cols: list[str],
    source_name: str = "IMPORT",
) -> str:
    """
    DROP and CREATE dataview.dv_stg_{target} with:
      - _stg_row_id INT IDENTITY(1,1) PRIMARY KEY
      - _stg_source NVARCHAR(40)  — dataset identifier
      - _stg_loaded_at DATETIME2  — load timestamp
      - one NVARCHAR(500) column per mapped source column
    Returns staging table name.
    """
    stg = f"dv_stg_{target_table.replace('dv_', '', 1)}"
    full = f"[dataview].[{stg}]"

    col_defs = "\n".join(
        f"    [{c}] NVARCHAR(500) NULL," for c in mapped_cols
    )

    ddl = f"""
        IF OBJECT_ID('{full}', 'U') IS NOT NULL DROP TABLE {full};
        CREATE TABLE {full} (
            [_stg_row_id]    INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
            [_stg_source]    NVARCHAR(40)  NULL,
            [_stg_loaded_at] DATETIME2     DEFAULT GETDATE(),
{col_defs}
        );
    """
    with engine.begin() as con:
        con.execute(text(ddl))
    return stg


# =============================================================================
# STAGE 3 — BULK INSERT INTO STAGING
# =============================================================================

def bulk_insert_stg(
    engine,
    df: pd.DataFrame,
    stg_table: str,
    mapped_cols: list[str],
    source_name: str = "IMPORT",
) -> int:
    """
    BULK INSERT df into dataview.{stg_table}.

    Strategy:
      1. Write TSV with data columns only (no identity, no audit cols)
      2. BULK INSERT into a temp table #_stg_tmp with matching columns
      3. INSERT INTO staging SELECT source + GETDATE() + cols FROM #_stg_tmp
         — SQL Server auto-generates _stg_row_id (IDENTITY)

    Returns rows inserted.
    """
    full     = f"[dataview].[{stg_table}]"
    tmp_path = None

    try:
        # Write TSV — data columns only
        out = df[mapped_cols].copy().fillna("").astype(str)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".tsv", delete=False,
            encoding="utf-8", newline=""
        ) as tmp:
            tmp_path = tmp.name
            out.to_csv(tmp, index=False, header=False,
                       na_rep="", sep="\t",
                       quoting=csv.QUOTE_MINIMAL)

        # Temp table DDL — data columns only, no identity
        col_defs = "\n".join(
            f"    [{c}] NVARCHAR(500) NULL," for c in mapped_cols
        ).rstrip(",")
        create_tmp = f"""
            IF OBJECT_ID('tempdb..#_stg_tmp', 'U') IS NOT NULL
                DROP TABLE #_stg_tmp;
            CREATE TABLE #_stg_tmp (
{col_defs}
            );
        """

        bulk_sql = (
            f"BULK INSERT #_stg_tmp "
            f"FROM '{tmp_path}' "
            "WITH (FIELDTERMINATOR='\t', ROWTERMINATOR='\n', "
            "KEEPNULLS, CODEPAGE='65001')"
        )

        data_cols   = ", ".join(f"[{c}]" for c in mapped_cols)
        insert_sql  = f"""
            INSERT INTO {full}
                ([_stg_source], [_stg_loaded_at], {data_cols})
            SELECT
                '{source_name}', GETDATE(), {data_cols}
            FROM #_stg_tmp;
            DROP TABLE #_stg_tmp;
        """

        with engine.begin() as con:
            con.execute(text(create_tmp))
            con.execute(text(bulk_sql))
            con.execute(text(insert_sql))

        with engine.connect() as con:
            n = con.execute(text(
                f"SELECT COUNT(*) FROM {full}"
            )).scalar()
        return n

    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# =============================================================================
# STAGE 4 — NORMALIZE STAGING TABLE
# =============================================================================


def bulk_insert_from_csv(
    engine,
    file_path: str,
    stg_table: str,
    mapped_cols: list[str],
    all_file_cols: list[str],
    source_name: str = "IMPORT",
    delimiter: str = ",",
) -> int:
    """Direct BULK INSERT from file — no pandas needed."""
    full       = f"[dataview].[{stg_table}]"
    fp_escaped = file_path.replace("'", "''")
    delim_sql  = "\t" if delimiter in ("\t", "\\t", "tab") else delimiter.replace("'", "''")

    raw_col_defs    = ",\n    ".join(f"[{c}] NVARCHAR(500)" for c in all_file_cols)
    mapped_col_list = ", ".join(f"[{c}]" for c in mapped_cols)
    stg_col_list    = f"[_stg_source], {mapped_col_list}"

    bulk_sql = (
        f"CREATE TABLE #raw (\n    {raw_col_defs}\n);\n"
        f"BULK INSERT #raw\n"
        f"FROM '{fp_escaped}'\n"
        f"WITH (FIELDTERMINATOR='{delim_sql}', ROWTERMINATOR='\\n',\n"
        f"      FIELDQUOTE='\"', FIRSTROW=2, KEEPNULLS, CODEPAGE='65001');\n"
        f"INSERT INTO {full} ({stg_col_list}, [_stg_loaded_at])\n"
        f"SELECT '{source_name}', {mapped_col_list}, GETDATE() FROM #raw;\n"
        f"DROP TABLE #raw;"
    )

    with engine.begin() as con:
        con.execute(text(bulk_sql))

    with engine.connect() as con:
        return con.execute(text(f"SELECT COUNT(*) FROM {full}")).scalar()

def normalize_stg(
    engine,
    stg_table: str,
    df_sample: pd.DataFrame,
    uwi_src_col: str | None = None,
) -> dict:
    """
    Run server-side normalization on the staging table.
    Reuses normalize.py's build_normalize_sql().
    If uwi_src_col provided, also normalizes UWI to 14-digit no-dash format.
    Returns {transforms_applied, changes}.
    """
    full = f"[dataview].[{stg_table}]"
    total_stmts = 0

    try:
        from normalize import build_normalize_sql
        schema_col_types = {c: "NVARCHAR(500)" for c in df_sample.columns}
        stmts = build_normalize_sql(
            stg_table,
            list(df_sample.columns),
            schema_col_types,
            schema="dataview",
            df_sample=df_sample,
        )
        with engine.begin() as con:
            for sql in stmts:
                con.execute(text(sql))
        total_stmts += len(stmts)
    except ImportError:
        pass  # normalize.py optional — continue with UWI norm
    except Exception as e:
        return {"ok": False, "transforms": 0, "error": str(e)}

    # ── UWI normalization — strip dashes/prefix, pad to 14 digits ────
    if uwi_src_col:
        try:
            uwi_norm_sql = f"""
                UPDATE {full}
                SET [{uwi_src_col}] =
                    -- Strip non-numeric, pad/truncate to 14 digits
                    CASE
                        -- Already 14 digits of pure numbers
                        WHEN LEN(REPLACE(REPLACE(REPLACE(REPLACE(
                             [{uwi_src_col}],'-',''),' ',''),'.',''),'US','')) = 14
                        THEN REPLACE(REPLACE(REPLACE(REPLACE(
                             [{uwi_src_col}],'-',''),' ',''),'.',''),'US','')

                        -- 10 digits → pad 4 zeros
                        WHEN LEN(REPLACE(REPLACE(REPLACE(REPLACE(
                             [{uwi_src_col}],'-',''),' ',''),'.',''),'US','')) = 10
                        THEN REPLACE(REPLACE(REPLACE(REPLACE(
                             [{uwi_src_col}],'-',''),' ',''),'.',''),'US','') + '0000'

                        -- 12 digits → pad 2 zeros
                        WHEN LEN(REPLACE(REPLACE(REPLACE(REPLACE(
                             [{uwi_src_col}],'-',''),' ',''),'.',''),'US','')) = 12
                        THEN REPLACE(REPLACE(REPLACE(REPLACE(
                             [{uwi_src_col}],'-',''),' ',''),'.',''),'US','') + '00'

                        -- 16 digits → truncate to 14
                        WHEN LEN(REPLACE(REPLACE(REPLACE(REPLACE(
                             [{uwi_src_col}],'-',''),' ',''),'.',''),'US','')) = 16
                        THEN LEFT(REPLACE(REPLACE(REPLACE(REPLACE(
                             [{uwi_src_col}],'-',''),' ',''),'.',''),'US',''), 14)

                        -- 15 digits with leading zero → strip to 14
                        WHEN LEN(REPLACE(REPLACE(REPLACE(REPLACE(
                             [{uwi_src_col}],'-',''),' ',''),'.',''),'US','')) = 15
                             AND LEFT(REPLACE(REPLACE(REPLACE(REPLACE(
                             [{uwi_src_col}],'-',''),' ',''),'.',''),'US',''),1) = '0'
                        THEN RIGHT(REPLACE(REPLACE(REPLACE(REPLACE(
                             [{uwi_src_col}],'-',''),' ',''),'.',''),'US',''), 14)

                        -- Keep 15-digit as-is (genuine KGS/agency format)
                        WHEN LEN(REPLACE(REPLACE(REPLACE(REPLACE(
                             [{uwi_src_col}],'-',''),' ',''),'.',''),'US','')) = 15
                        THEN REPLACE(REPLACE(REPLACE(REPLACE(
                             [{uwi_src_col}],'-',''),' ',''),'.',''),'US','')

                        ELSE [{uwi_src_col}]  -- leave unchanged if unrecognised
                    END
                WHERE [{uwi_src_col}] IS NOT NULL
            """
            with engine.begin() as con:
                con.execute(text(uwi_norm_sql))
            total_stmts += 1
        except Exception as e:
            return {"ok": False, "transforms": total_stmts,
                    "error": f"UWI normalization failed: {e}"}

    return {"ok": True, "transforms": total_stmts, "error": None}




# =============================================================================
# STAGE 4b — APPLY FK RESOLUTIONS TO STAGING (before validation)
# =============================================================================

def apply_fk_resolutions_stg(
    engine,
    stg_table: str,
    col_map: dict,       # {target_col: source_col}
    fk_resolutions: dict,  # {target_col: {raw_val: resolved_val}}
) -> dict:
    """
    Apply stored FK value resolutions as UPDATEs to the staging table.
    Must run AFTER normalize_stg() and BEFORE validate_stg().

    fk_resolutions format:
        {
          "well_type":   {"GAS WELL": "GAS", "OIL WELL": "OIL"},
          "well_status": {"PLUG": "PLUGGED", "OPEN": "ACTIVE"},
        }

    Returns {"applied": n_updates, "nulled": n_nulled, "errors": [...]}
    """
    full   = f"[dataview].[{stg_table}]"
    stg_cols = _get_stg_cols(engine, stg_table)
    applied = 0
    nulled  = 0
    errors  = []

    for tgt_col, mappings in fk_resolutions.items():
        src_col = col_map.get(tgt_col)
        if not src_col or src_col not in stg_cols:
            continue

        for raw_val, resolved in mappings.items():
            try:
                with engine.begin() as con:
                    if resolved is None or str(resolved).upper() in ("NULL", ""):
                        # Null out unresolvable values
                        con.execute(text(f"""
                            UPDATE {full}
                            SET [{src_col}] = NULL
                            WHERE UPPER(LTRIM(RTRIM([{src_col}])))
                                  = UPPER(:raw)
                        """), {"raw": str(raw_val)})
                        nulled += 1
                    else:
                        # Map to canonical value
                        con.execute(text(f"""
                            UPDATE {full}
                            SET [{src_col}] = :resolved
                            WHERE UPPER(LTRIM(RTRIM([{src_col}])))
                                  = UPPER(:raw)
                        """), {"resolved": str(resolved),
                               "raw": str(raw_val)})
                        applied += 1
            except Exception as e:
                errors.append(f"{tgt_col} {raw_val!r}→{resolved!r}: {e}")

    return {"applied": applied, "nulled": nulled, "errors": errors}


# =============================================================================
# STAGE 5 — VALIDATE STAGING TABLE
# =============================================================================

@dataclass
class ValidationSummary:
    ok:           bool
    rows_checked: int
    error_count:  int
    warning_count: int
    issues:       list[dict] = field(default_factory=list)
    bad_row_ids:  list[int]  = field(default_factory=list)  # ERROR rows only
    warn_row_ids: list[int]  = field(default_factory=list)  # WARNING rows only

    @property
    def reject_row_ids(self) -> list[int]:
        """Only ERROR rows go to rejection file — warnings still promote."""
        return self.bad_row_ids

    @property
    def clean_count(self) -> int:
        """Rows that will promote = total minus error rows."""
        return self.rows_checked - len(set(self.bad_row_ids))

    def to_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.issues) if self.issues else pd.DataFrame(
            columns=["rule", "severity", "ppdm_col", "message", "count"])


def validate_stg(
    engine,
    stg_table: str,
    target_table: str,
    col_map: dict[str, str],  # {target_col: source_col}
) -> ValidationSummary:
    """
    Run validation checks on the staging table.
    Returns ValidationSummary with issue list and bad _stg_row_ids.
    """
    full = f"[dataview].[{stg_table}]"
    issues = []
    bad_ids: set[int] = set()

    with engine.connect() as con:
        total = con.execute(text(f"SELECT COUNT(*) FROM {full}")).scalar()

    # ── 1. UWI format check (if uwi mapped) ──────────────────────────
    uwi_col = col_map.get("uwi")
    if uwi_col and uwi_col in _get_stg_cols(engine, stg_table):
        with engine.connect() as con:
            bad_uwi = con.execute(text(f"""
                SELECT _stg_row_id FROM {full}
                WHERE [{uwi_col}] IS NOT NULL
                AND LTRIM(RTRIM([{uwi_col}])) <> ''
                AND (
                    -- Must be 14 or 15 pure digits after normalization
                    LEN([{uwi_col}]) NOT IN (14, 15)
                    OR [{uwi_col}] LIKE '%[^0-9]%'
                )
            """)).fetchall()
        if bad_uwi:
            issues.append({
                "rule": "UWI_FORMAT", "severity": "WARNING",
                "ppdm_col": "uwi",
                "message": (f"UWI not 14-digit no-dash format: "
                            f"{len(bad_uwi):,} rows — check API_NUM column"),
                "count": len(bad_uwi),
            })

    # ── 2. Lat/lon range checks ───────────────────────────────────────
    lat_col = col_map.get("surface_latitude")
    lon_col = col_map.get("surface_longitude")
    stg_cols = _get_stg_cols(engine, stg_table)

    if lat_col and lat_col in stg_cols:
        with engine.connect() as con:
            bad_lat = con.execute(text(f"""
                SELECT _stg_row_id FROM {full}
                WHERE [{lat_col}] IS NOT NULL
                AND LTRIM(RTRIM([{lat_col}])) <> ''
                AND (TRY_CONVERT(float, [{lat_col}]) IS NULL
                     OR TRY_CONVERT(float, [{lat_col}]) < -90
                     OR TRY_CONVERT(float, [{lat_col}]) > 90)
            """)).fetchall()
        if bad_lat:
            for r in bad_lat:
                bad_ids.add(r[0])
            issues.append({
                "rule": "LAT_RANGE", "severity": "ERROR",
                "ppdm_col": "surface_latitude",
                "message": f"Latitude out of range (-90 to 90): {len(bad_lat):,} rows",
                "count": len(bad_lat),
            })

    if lon_col and lon_col in stg_cols:
        with engine.connect() as con:
            bad_lon = con.execute(text(f"""
                SELECT _stg_row_id FROM {full}
                WHERE [{lon_col}] IS NOT NULL
                AND LTRIM(RTRIM([{lon_col}])) <> ''
                AND (TRY_CONVERT(float, [{lon_col}]) IS NULL
                     OR TRY_CONVERT(float, [{lon_col}]) < -180
                     OR TRY_CONVERT(float, [{lon_col}]) > 180)
            """)).fetchall()
        if bad_lon:
            for r in bad_lon:
                bad_ids.add(r[0])
            issues.append({
                "rule": "LON_RANGE", "severity": "ERROR",
                "ppdm_col": "surface_longitude",
                "message": f"Longitude out of range (-180 to 180): {len(bad_lon):,} rows",
                "count": len(bad_lon),
            })

    # ── 3. Spud before completion ─────────────────────────────────────
    spud_col = col_map.get("spud_date")
    comp_col = col_map.get("completion_date")
    if spud_col and comp_col and spud_col in stg_cols and comp_col in stg_cols:
        with engine.connect() as con:
            bad_dates = con.execute(text(f"""
                SELECT _stg_row_id FROM {full}
                WHERE [{spud_col}] IS NOT NULL
                AND [{comp_col}] IS NOT NULL
                AND TRY_CONVERT(date, [{spud_col}]) IS NOT NULL
                AND TRY_CONVERT(date, [{comp_col}]) IS NOT NULL
                AND TRY_CONVERT(date, [{spud_col}]) > TRY_CONVERT(date, [{comp_col}])
            """)).fetchall()
        if bad_dates:
            issues.append({
                "rule": "SPUD_BEFORE_COMPLETION", "severity": "WARNING",
                "ppdm_col": "spud_date",
                "message": f"Spud date after completion date: {len(bad_dates):,} rows",
                "count": len(bad_dates),
            })

    # ── 4. Duplicate PK check ─────────────────────────────────────────
    pk_cols = _SchemaCache.table_pk(target_table)
    mapped_pks = [col_map.get(pk.lower()) for pk in pk_cols
                  if col_map.get(pk.lower()) and col_map.get(pk.lower()) in stg_cols]
    if len(mapped_pks) == len(pk_cols) and mapped_pks:
        pk_list = ", ".join(f"[{c}]" for c in mapped_pks)
        with engine.connect() as con:
            dup_count = con.execute(text(f"""
                SELECT COUNT(*) FROM (
                    SELECT {pk_list} FROM {full}
                    GROUP BY {pk_list}
                    HAVING COUNT(*) > 1
                ) x
            """)).scalar()
        if dup_count:
            issues.append({
                "rule": "DUPLICATE_PK", "severity": "ERROR",
                "ppdm_col": "+".join(pk_cols),
                "message": f"Duplicate primary key combinations: {dup_count:,}",
                "count": dup_count,
            })

    # ── 5. Numeric type checks for known numeric target cols ──────────
    tbl_cols = _SchemaCache.table_cols(target_table)
    for tgt_col, src_col in col_map.items():
        if src_col not in stg_cols:
            continue
        dtype = tbl_cols.get(tgt_col.upper(), "")
        if any(t in dtype.upper() for t in ("DECIMAL", "NUMERIC", "FLOAT", "INT")):
            with engine.connect() as con:
                bad_num = con.execute(text(f"""
                    SELECT COUNT(*) FROM {full}
                    WHERE [{src_col}] IS NOT NULL
                    AND LTRIM(RTRIM([{src_col}])) <> ''
                    AND TRY_CONVERT(float, [{src_col}]) IS NULL
                """)).scalar()
            if bad_num:
                issues.append({
                    "rule": "TYPE_CHECK", "severity": "ERROR",
                    "ppdm_col": tgt_col,
                    "message": f"Non-numeric value in {tgt_col} ({dtype}): "
                               f"{bad_num:,} rows",
                    "count": bad_num,
                })

    # ── 6. FK violation checks ───────────────────────────────────────
    fk_issues = _check_fk_violations(engine, stg_table, target_table, col_map)
    issues.extend(fk_issues)

    error_count   = sum(i["count"] for i in issues if i["severity"] == "ERROR")
    warning_count = sum(i["count"] for i in issues if i["severity"] == "WARNING")

    return ValidationSummary(
        ok=error_count == 0,
        rows_checked=total,
        error_count=error_count,
        warning_count=warning_count,
        issues=issues,
        bad_row_ids=list(bad_ids),
        warn_row_ids=[],
    )


def _check_fk_violations(
    engine,
    stg_table: str,
    target_table: str,
    col_map: dict,
) -> list[dict]:
    """
    Server-side FK violation check using sys.foreign_keys.
    For each FK on target_table that maps to a staged column,
    find values in staging that don't exist in the parent table.
    Returns list of issue dicts compatible with ValidationSummary.
    Only checks FKs where the child column is mapped in col_map.
    Does NOT add to bad_row_ids — FK violations are ERRORs but
    resolvable via apply_fk_resolutions_stg().
    """
    full    = f"[dataview].[{stg_table}]"
    stg_cols = _get_stg_cols(engine, stg_table)
    issues  = []

    try:
        # Get FK constraints from sys.foreign_keys for this table
        with engine.connect() as con:
            fk_rows = con.execute(text("""
                SELECT
                    fkc.parent_column_id,
                    cc.name          AS child_col,
                    OBJECT_NAME(fk.referenced_object_id) AS parent_tbl,
                    pc.name          AS parent_col,
                    fk.name          AS fk_name
                FROM sys.foreign_keys fk
                JOIN sys.foreign_key_columns fkc
                    ON fkc.constraint_object_id = fk.object_id
                JOIN sys.columns cc
                    ON cc.object_id = fkc.parent_object_id
                    AND cc.column_id = fkc.parent_column_id
                JOIN sys.columns pc
                    ON pc.object_id = fkc.referenced_object_id
                    AND pc.column_id = fkc.referenced_column_id
                WHERE OBJECT_NAME(fk.parent_object_id) = :tbl
                  AND SCHEMA_NAME(fk.schema_id) = 'dataview'
            """), {"tbl": target_table}).fetchall()
    except Exception:
        return []

    # Entity FK columns are seeded automatically in Stage 7 — skip here
    _ENTITY_FK_COLS = {
        "operator_ba_id", "current_operator_ba_id",
        "original_operator_ba_id", "field_id",
    }

    for _, child_col, parent_tbl, parent_col, fk_name in fk_rows:
        # Find if this FK column is mapped from staging
        src_col = col_map.get(child_col.lower())
        if not src_col or src_col not in stg_cols:
            continue

        # Skip self-referencing FKs (e.g. source → r_source)
        if parent_tbl.lower() == target_table.lower():
            continue

        # Skip entity FKs — seeded automatically from staging values
        if child_col.lower() in _ENTITY_FK_COLS:
            continue

        try:
            with engine.connect() as con:
                # Count staging rows whose value is not in parent table
                bad_count = con.execute(text(f"""
                    SELECT COUNT(DISTINCT s.[{src_col}])
                    FROM {full} s
                    WHERE s.[{src_col}] IS NOT NULL
                      AND LTRIM(RTRIM(s.[{src_col}])) <> ''
                      AND NOT EXISTS (
                          SELECT 1
                          FROM [dataview].[{parent_tbl}] p
                          WHERE UPPER(LTRIM(RTRIM(p.[{parent_col}])))
                              = UPPER(LTRIM(RTRIM(s.[{src_col}])))
                      )
                """)).scalar() or 0

                if bad_count == 0:
                    continue

                # Get the distinct bad values (up to 20)
                bad_vals = [r[0] for r in con.execute(text(f"""
                    SELECT DISTINCT TOP 20 s.[{src_col}]
                    FROM {full} s
                    WHERE s.[{src_col}] IS NOT NULL
                      AND LTRIM(RTRIM(s.[{src_col}])) <> ''
                      AND NOT EXISTS (
                          SELECT 1
                          FROM [dataview].[{parent_tbl}] p
                          WHERE UPPER(LTRIM(RTRIM(p.[{parent_col}])))
                              = UPPER(LTRIM(RTRIM(s.[{src_col}])))
                      )
                """)).fetchall()]

            issues.append({
                "rule":        "FK_VIOLATION",
                "severity":    "ERROR",
                "ppdm_col":    child_col.lower(),
                "src_col":     src_col,
                "parent_table":parent_tbl,
                "parent_col":  parent_col,
                "message":     (
                    f"FK violation: {child_col} → "
                    f"{parent_tbl}.{parent_col} — "
                    f"{bad_count} unknown value(s)"
                ),
                "count":       bad_count,
                "bad_values":  bad_vals,
            })

        except Exception as e:
            # Non-fatal — skip this FK check if query fails
            issues.append({
                "rule":     "FK_CHECK_ERROR",
                "severity": "WARNING",
                "ppdm_col": child_col.lower(),
                "message":  f"FK check failed for {child_col}: {e}",
                "count":    0,
                "bad_values": [],
            })

    return issues


def _get_stg_cols(engine, stg_table: str) -> set[str]:
    """Return column names in the staging table."""
    with engine.connect() as con:
        rows = con.execute(text("""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA='dataview' AND TABLE_NAME=:tbl
        """), {"tbl": stg_table}).fetchall()
    return {r[0] for r in rows}


# =============================================================================
# STAGE 6 — APPLY CODE MAPS TO STAGING
# =============================================================================

def apply_code_maps(
    engine,
    stg_table: str,
    col_map: dict[str, str],   # {target_col: source_col}
    rules: dict,               # from Rules Engine session state
) -> int:
    """
    UPDATE staging table: apply code maps for well_type, well_status, etc.
    Returns number of UPDATE statements executed.
    """
    full = f"[dataview].[{stg_table}]"
    stg_cols = _get_stg_cols(engine, stg_table)
    updates = 0

    for tgt_col, src_col in col_map.items():
        if src_col not in stg_cols:
            continue
        code_map = rules.get(f"map_{tgt_col}", {})
        if not code_map:
            continue

        with engine.begin() as con:
            for raw_val, canonical in code_map.items():
                con.execute(text(f"""
                    UPDATE {full}
                    SET [{src_col}] = :canonical
                    WHERE UPPER(LTRIM(RTRIM([{src_col}]))) = UPPER(:raw)
                """), {"canonical": canonical, "raw": raw_val})
        updates += 1

    return updates


# =============================================================================
# STAGE 7 — SEED ENTITIES FROM STAGING
# =============================================================================

def seed_entities_from_stg(
    engine,
    stg_table: str,
    target_table: str,
    col_map: dict[str, str],
    source_name: str = "IMPORT",
    ba_type: str = "COMPANY",
) -> dict:
    """
    Seed dv_business_associate and dv_field from staging table.
    Returns {ba_seeded, fields_seeded}.
    """
    full = f"[dataview].[{stg_table}]"
    stg_cols = _get_stg_cols(engine, stg_table)
    ba_seeded = 0
    fields_seeded = 0

    # Validate source_name against dv_r_source
    _valid_src = source_name
    try:
        with engine.connect() as _sc:
            _exists = _sc.execute(text(
                "SELECT COUNT(*) FROM dataview.dv_r_source WHERE source = :s"),
                {"s": source_name}).scalar()
            if not _exists:
                _valid_src = "IMPORT"
    except Exception:
        _valid_src = "IMPORT"

    # Business associates
    ba_targets = {"operator_ba_id", "current_operator_ba_id",
                  "original_operator_ba_id"}
    for tgt, src in col_map.items():
        if tgt not in ba_targets or src not in stg_cols:
            continue
        # Get distinct names from staging
        with engine.connect() as con:
            names = [r[0] for r in con.execute(text(f"""
                SELECT DISTINCT [{src}] FROM {full}
                WHERE [{src}] IS NOT NULL
                AND LTRIM(RTRIM([{src}])) <> ''
            """)).fetchall()]

        with engine.begin() as con:
            for name in names:
                ba_id = hashlib.sha1(name.encode()).hexdigest()[:40]
                try:
                    con.execute(text("""
                        IF NOT EXISTS (SELECT 1 FROM dataview.dv_business_associate
                                       WHERE ba_id = :bid)
                        INSERT INTO dataview.dv_business_associate
                            (ba_id, ba_name, ba_type, active_ind,
                             row_created_by, row_created_date, source)
                        VALUES (:bid, :name, :btype, 'Y', :src, GETDATE(), :src)
                    """), {"bid": ba_id, "name": name,
                           "btype": ba_type, "src": _valid_src})
                    ba_seeded += 1
                except Exception:
                    pass

        # UPDATE staging: replace name with ba_id
        with engine.begin() as con:
            con.execute(text(f"""
                UPDATE stg
                SET stg.[{src}] = ba.ba_id
                FROM {full} stg
                JOIN dataview.dv_business_associate ba
                  ON ba.ba_name = stg.[{src}]
            """))

    # Fields
    field_src = col_map.get("field_id")
    if field_src and field_src in stg_cols:
        with engine.connect() as con:
            field_names = [r[0] for r in con.execute(text(f"""
                SELECT DISTINCT [{field_src}] FROM {full}
                WHERE [{field_src}] IS NOT NULL
                AND LTRIM(RTRIM([{field_src}])) <> ''
            """)).fetchall()]

        with engine.begin() as con:
            for name in field_names:
                fid = hashlib.sha1(name.encode()).hexdigest()[:40]
                try:
                    con.execute(text("""
                        IF NOT EXISTS (SELECT 1 FROM dataview.dv_field
                                       WHERE field_id = :fid)
                        INSERT INTO dataview.dv_field
                            (field_id, field_name, active_ind,
                             row_created_by, row_created_date, source)
                        VALUES (:fid, :name, 'Y', :src, GETDATE(), :src)
                    """), {"fid": fid, "name": name, "src": _valid_src})
                    fields_seeded += 1
                except Exception:
                    pass

        with engine.begin() as con:
            con.execute(text(f"""
                UPDATE stg
                SET stg.[{field_src}] = f.field_id
                FROM {full} stg
                JOIN dataview.dv_field f ON f.field_name = stg.[{field_src}]
            """))

    return {"ba_seeded": ba_seeded, "fields_seeded": fields_seeded}


# =============================================================================
# STAGE 8 — PROMOTE STAGING → TARGET
# =============================================================================

@dataclass
class PromoteResult:
    ok:            bool
    inserted:      int = 0
    skipped:       int = 0
    rejected:      int = 0
    reject_file:   str = ""
    error:         str = ""
    sql_executed:  str = ""


def promote_stg(
    engine,
    stg_table: str,
    target_table: str,
    col_map: dict[str, str],      # {target_col: source_col}
    rules: dict,
    bad_row_ids: list[int],
    source_name: str = "IMPORT",
    reject_dir: str = "rejections",
) -> PromoteResult:
    """
    INSERT INTO target SELECT FROM staging WHERE _stg_row_id NOT IN (bad_ids).
    Bad rows written to rejection CSV.
    Duplicate PKs excluded via NOT EXISTS.
    Returns PromoteResult.
    """
    full_stg = f"[dataview].[{stg_table}]"
    full_tgt = f"[dataview].[{target_table}]"
    stg_cols = _get_stg_cols(engine, stg_table)

    with engine.connect() as con:
        total = con.execute(text(f"SELECT COUNT(*) FROM {full_stg}")).scalar()

    # Resolve constants from rules
    const_source = (rules.get("const_source", {}).get("value") or source_name)
    const_active = rules.get("const_active_ind", {}).get("value", "Y")

    # Build column pairs — only mapped cols that exist in staging
    pairs = []
    for tgt_col, src_col in col_map.items():
        if tgt_col in _AUDIT_COLS:
            continue
        if src_col in stg_cols:
            pairs.append((tgt_col, src_col))

    if not pairs:
        return PromoteResult(ok=False, error="No active column mappings")

    # Apply constant overrides for unmapped audit cols
    tgt_cols_sql = ", ".join(f"[{tgt}]" for tgt, _ in pairs)
    tgt_cols_sql += (", [active_ind], [source], "
                     "[row_created_by], [row_created_date], "
                     "[row_changed_by], [row_changed_date]")

    src_cols_sql = ", ".join(
        f"NULLIF(LTRIM(RTRIM([{src}])), '') AS [{tgt}]"
        for tgt, src in pairs
    )
    src_cols_sql += (f", '{const_active}', '{const_source}', "
                     f"'{source_name}', GETDATE(), '{source_name}', GETDATE()")

    # PK duplicate exclusion
    pk_cols = _SchemaCache.table_pk(target_table)
    mapped_pks = [(pk, col_map.get(pk.lower()))
                  for pk in pk_cols if col_map.get(pk.lower())]

    not_exists_clause = ""
    if mapped_pks:
        join_conds = " AND ".join(
            f"t.[{pk}] = s.[{src}]"
            for pk, src in mapped_pks
        )
        not_exists_clause = (
            f"WHERE NOT EXISTS ("
            f"SELECT 1 FROM {full_tgt} t WHERE {join_conds})"
        )

    # Exclude bad rows
    bad_ids_clause = ""
    if bad_row_ids:
        ids_str = ", ".join(str(i) for i in bad_row_ids)
        bad_ids_clause = (
            f"AND [_stg_row_id] NOT IN ({ids_str})"
            if not_exists_clause
            else f"WHERE [_stg_row_id] NOT IN ({ids_str})"
        )

    promote_sql = (
        f"INSERT INTO {full_tgt} ({tgt_cols_sql}) "
        f"SELECT {src_cols_sql} FROM {full_stg} s "
        f"{not_exists_clause} {bad_ids_clause}"
    )

    import logging, time as _time
    _log = logging.getLogger("dv_promote")
    logging.basicConfig(level=logging.DEBUG)

    reject_file = ""

    _log.debug("PROMOTE: writing rejection CSV...")
    t0 = _time.time()
    try:
        if bad_row_ids:
            reject_file = _write_reject_csv(
                engine, full_stg, bad_row_ids, target_table,
                source_name, reject_dir
            )
        _log.debug(f"PROMOTE: reject CSV done in {_time.time()-t0:.1f}s — {reject_file}")
    except Exception as _e:
        _log.debug(f"PROMOTE: reject CSV failed: {_e}")

    _log.debug(f"PROMOTE: executing INSERT... sql={promote_sql[:100]}")
    t0 = _time.time()
    try:
        with engine.begin() as con:
            con.execute(text(promote_sql))
        _log.debug(f"PROMOTE: INSERT done in {_time.time()-t0:.1f}s")

        inserted = total - len(set(bad_row_ids))
        _log.debug(f"PROMOTE: returning result inserted={inserted}")

        return PromoteResult(
            ok=True,
            inserted=inserted,
            skipped=len(bad_row_ids),
            rejected=len(bad_row_ids),
            reject_file=reject_file,
            sql_executed=promote_sql[:200],
        )

    except Exception as e:
        _log.debug(f"PROMOTE: INSERT failed: {e}")
        return PromoteResult(ok=False, error=str(e),
                             sql_executed=promote_sql[:200])


def _write_reject_csv(
    engine,
    full_stg: str,
    bad_row_ids: list[int],
    target_table: str,
    source_name: str,
    reject_dir: str,
) -> str:
    """Write bad rows to a dated rejection CSV. Returns file path."""
    try:
        Path(reject_dir).mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        fname = f"{reject_dir}/{target_table}_{source_name}_{ts}_rejected.csv"

        ids_str = ", ".join(str(i) for i in bad_row_ids)
        with engine.connect() as con:
            df = pd.read_sql(
                f"SELECT * FROM {full_stg} "
                f"WHERE _stg_row_id IN ({ids_str})",
                con
            )
        df.to_csv(fname, index=False)
        return fname
    except Exception:
        return ""
