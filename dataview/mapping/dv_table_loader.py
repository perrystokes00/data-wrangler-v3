"""
dv_table_loader.py — config-driven loader for PPDM-style table CSVs -> dv_*.

THREE LAYERS (the FK refactor):
  1. FK STRUCTURE is DISCOVERED from the database (sys.foreign_keys) at run
     time — never hand-written. The DB already owns "which column points where."
  2. FK POLICY is DECLARED once, keyed by the REFERENCED table, from a fixed
     vocabulary of strategies. This is the human intent the DB can't infer.
  3. A generic RESOLVER joins discovered FKs to the policy and applies it.

  Net effect: a per-table TableSpec carries only column-map + natural key +
  (for entity FKs) which source column feeds which id. Everything FK is the
  policy's job. Most of the 159 FKs point at a handful of tables, so the whole
  policy is a few lines.

POLICY VOCABULARY:
  SEED_ENTITY  name -> SHA1 id, insert missing parent   (dv_business_associate, dv_field)
  SEED_CODE    distinct code value, insert missing      (dv_r_*)
  CONFORM      map/normalize, then require exists, halt  (dv_country/province_state/county)
  STRICT       must already exist, halt on miss          (parent dv_well)
  DEFER        load NULL, skip the column

CONVENTIONS: bare-14 UWI (path_identity.norm_uwi14); SHA1 entity ids exactly per
entity_seeder (sha1(name.strip().encode('utf-8')).hexdigest()); set-based only;
unmatched STRICT/CONFORM halt & audit, never null; idempotent NOT-EXISTS insert.
Seeding self-guards: it introspects the parent's required (NOT NULL / no-default)
columns and refuses to seed (halt-audit) rather than blow up on a column it can't fill.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import event
from sqlalchemy import text as _t

try:
    from dataview.core import fk_resolution as _fkr          # value-level FK reconciliation (optional)
except Exception:
    _fkr = None


# ── POLICY: referenced-table -> (strategy, params) ───────────────────────────
FK_POLICY = {
    "dv_business_associate": ("SEED_ENTITY", {"name_col": "ba_name"}),
    "dv_field":              ("SEED_ENTITY", {"name_col": "field_name"}),
    "dv_country":            ("DEFER", {}),     # geo: flip to CONFORM once crosswalked
    "dv_province_state":     ("DEFER", {}),
    "dv_county":             ("DEFER", {}),
    "dv_well":               ("STRICT", {}),    # the well parent for detail tables
}
FK_POLICY_PREFIX = {
    # Controlled-vocabulary code tables: STRICT by default — an unknown code
    # HALTS and is audited, it is NOT auto-admitted. Populate these deliberately
    # from authoritative PPDM reference data (Standards Manager). Use CONFORM
    # (with a crosswalk) for known source->canonical variants, or override a
    # specific table to SEED_CODE only when bootstrapping from a trusted source.
    "dv_r_": ("STRICT", {}),
}
FK_DEFAULT = ("STRICT", {})                     # anything unlisted must already exist

# Substring that identifies controlled-vocabulary code tables — those reconcile
# (offer add/remap) instead of hard-halting on an unknown value. Defaults to the
# DataView "dv_r_" convention; mapping_studio.configure() overrides this so a
# customer's reference tables (e.g. "ref_", "lookup_") get the same treatment.
REF_TABLE_PATTERN = "dv_r_"


def _policy_for(ref_table: str, spec) -> tuple:
    t = ref_table.split(".")[-1].lower()
    if spec is not None and t in spec.fk_overrides:
        return spec.fk_overrides[t]
    if t in FK_POLICY:
        return FK_POLICY[t]
    for pfx, strat in FK_POLICY_PREFIX.items():
        if t.startswith(pfx):
            return strat
    return FK_DEFAULT


# ── specs ────────────────────────────────────────────────────────────────────
@dataclass
class FKRef:
    name: str                 # constraint name
    ref_table: str            # "dataview.dv_business_associate"
    cols: list                # [(local_col, ref_col), ...]  (composite-aware)


@dataclass
class TableSpec:
    target:      str
    natural_key: list
    columns:     dict                                    # {source_col: target_col}
    constants:   dict = field(default_factory=dict)
    uwi_cols:    list = field(default_factory=list)
    seed_from:   dict = field(default_factory=dict)      # {target_id_col: source_name_col} (SEED_ENTITY)
    conform:     dict = field(default_factory=dict)      # {target_col: {raw: canonical}} (CONFORM)
    sequences:   list = field(default_factory=list)      # [target_col] generated 1..N within natural-key group (seq_within)
    fk_overrides: dict = field(default_factory=dict)     # {ref_table_name: (strategy, params)}
    parents:     list = field(default_factory=list)      # logical strict not DB-enforced: [(col, ref_table, ref_col)]


# ── REGISTRY ─────────────────────────────────────────────────────────────────
# Note how lean these are now: NO FK plumbing. The resolver discovers FKs and
# the policy decides. well_header re-enables the code columns (SEED_CODE handles
# them) and maps the geo columns (policy DEFER drops them until you crosswalk).
REGISTRY = {

    "well_header": TableSpec(
        target="dataview.dv_well",
        natural_key=["uwi"],
        columns={
            "UWI": "uwi", "WELL_NAME": "well_name", "OPERATOR": "operator_name",
            "WELL_CLASS": "well_type", "STATUS": "well_status",
            "DATA_SOURCE": "source", "DEPTH_DATUM": "depth_datum",
            "SPUD_DATE": "spud_date", "COMPLETION_DATE": "completion_date",
            "SURFACE_LATITUDE": "surface_latitude",
            "SURFACE_LONGITUDE": "surface_longitude",
            "DRILLERS_TD": "final_td", "KB_ELEV": "kb_elevation",
            "GL_ELEV": "ground_elevation", "FORMATION_AT_TD": "formation_at_td",
            "FIELD_NAME": "field_name",
            "COUNTRY": "country", "PROVINCE_STATE": "province_state",
            "COUNTY": "county",                      # geo -> DEFER drops these
        },
        constants={"active_ind": "Y", "row_created_by": "DV_TABLE_LOADER"},
        uwi_cols=["uwi"],
        seed_from={"operator_ba_id": "OPERATOR", "field_id": "FIELD_NAME"},
        # conform={"county": {"TX_MARTIN": "MARTIN", ...}},  # later, to flip geo to CONFORM
    ),

    "well_dir_survey_data": TableSpec(
        target="dataview.dv_well_dir_srvy_sta",
        natural_key=["uwi", "md"],
        columns={"UWI": "uwi", "MD": "md", "INC": "incl", "AZI": "azim", "TVD": "tvd"},
        constants={"source": "CSV_IMPORT", "row_created_by": "DV_TABLE_LOADER"},
        uwi_cols=["uwi"],
        parents=[("uwi", "dataview.dv_well", "uwi")],
    ),

    "well_picks": TableSpec(
        target="dataview.dv_well_formation_top",
        natural_key=["uwi", "strat_unit_name"],
        columns={"UWI": "uwi", "FORMATION": "strat_unit_name",
                 "MD": "top_depth", "TVD": "tvd_top"},
        constants={"active_ind": "Y", "source": "CSV_IMPORT",
                   "row_created_by": "DV_TABLE_LOADER"},
        uwi_cols=["uwi"],
        parents=[("uwi", "dataview.dv_well", "uwi")],
    ),

    "well_log_curve": TableSpec(
        target="dataview.dv_log_curve",
        natural_key=["UWI", "CURVE_MNEMONIC"],
        columns={"UWI": "UWI", "MNEMONIC": "CURVE_MNEMONIC",
                 "UNIT": "CURVE_UNIT", "DESCRIPTION": "CURVE_LONG_NAME"},
        constants={"SOURCE_FORMAT": "CSV", "ROW_CREATED_BY": "DV_TABLE_LOADER",
                   "ACTIVE_IND": "Y"},
        uwi_cols=["UWI"],
        parents=[("UWI", "dataview.dv_well", "uwi")],
    ),
}

ALIASES = {
    "well_dir_survey_hdr": "well_dir_survey_data",
    "well_dir_survey":     "well_dir_survey_data",
    "formation_tops":      "well_picks",
    "well_log":            "well_log_curve",
    "well_log_curves":     "well_log_curve",
}


# ── helpers ──────────────────────────────────────────────────────────────────
def _sha1_id(name):
    if name is None or str(name).strip() == "":
        return None
    return hashlib.sha1(str(name).strip().encode("utf-8")).hexdigest()


def _norm_uwi(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        from dataview.core import path_identity as _pi
        u = _pi.norm_uwi14(str(v))
        if u:
            return u
    except Exception:
        pass
    d = re.sub(r"\D", "", str(v))
    return d if len(d) == 14 else (d or None)


def _read_csv(path):
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        sample = fh.read(8192)
    delim = "\t" if path.lower().endswith(".tsv") else None
    if delim is None:
        try:
            delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except Exception:
            delim = ","
    return pd.read_csv(path, dtype=str, sep=delim, keep_default_na=False,
                       encoding="utf-8-sig").rename(columns=lambda c: c.strip())


def recognize(path):
    import os
    stem = os.path.splitext(os.path.basename(path))[0].strip().lower()
    return stem if stem in REGISTRY else ALIASES.get(stem)


def _seed_col(id_col):
    return "_seed_" + id_col


# ── discovery + introspection (cached) ───────────────────────────────────────
_FK_CACHE: dict = {}
_REQ_CACHE: dict = {}
_CATALOG = None

# Where to find the FK catalog JSON. First hit wins. Override with env
# DV_FK_CATALOG. Shapes accepted (see _normalize_catalog).
_CATALOG_NAMES = ("dataview_fk_catalog.json", "fk_catalog.json")


def _fk_catalog():
    """Load + normalize the FK catalog once. Returns {target_table: [FKRef,...]}.
    Empty dict if no catalog file is found (-> live discovery fallback)."""
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    if os.environ.get("DV_FK_CATALOG"):
        candidates.append(os.environ["DV_FK_CATALOG"])
    candidates += [os.path.join(here, n) for n in _CATALOG_NAMES]
    raw = None
    for p in candidates:
        if p and os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8-sig") as fh:
                    raw = json.load(fh)
                break
            except Exception:
                continue
    _CATALOG = _normalize_catalog(raw) if raw is not None else {}
    return _CATALOG


def _normalize_catalog(raw):
    """Accept a few plausible JSON shapes and return {target: [FKRef,...]}.

    Shape A (loader-native):
        {"dataview.dv_well": [{"name","ref_table","cols":[[local,ref],...]}, ...]}
    Shape B (flat list of FK rows):
        [{"parent_table","parent_column","ref_table","ref_column","name"?}, ...]
        (composite FKs share the same name; grouped here)
    """
    out: dict = {}
    if isinstance(raw, dict):
        for target, fks in raw.items():
            refs = []
            for i, e in enumerate(fks):
                refs.append(FKRef(e.get("name", f"fk{i}"), e["ref_table"],
                                  [tuple(c) for c in e["cols"]]))
            out[target] = refs
        return out
    if isinstance(raw, list):
        grouped: dict = {}
        for row in raw:
            pt = row.get("parent_table") or row.get("table")
            rt = row.get("ref_table") or row.get("referenced_table")
            pc = row.get("parent_column") or row.get("column")
            rc = row.get("ref_column") or row.get("referenced_column")
            nm = row.get("name") or row.get("fk_name") or f"{pt}->{rt}"
            if not (pt and rt and pc and rc):
                continue
            grouped.setdefault(pt, {}).setdefault(nm, {"ref": rt, "cols": []})
            grouped[pt][nm]["cols"].append((pc, rc))
        for pt, fks in grouped.items():
            out[pt] = [FKRef(nm, d["ref"], d["cols"]) for nm, d in fks.items()]
        return out
    return out


def discover_fks(engine, target):
    if target in _FK_CACHE:
        return _FK_CACHE[target]
    # 1) static JSON catalog — deterministic, matches the schema generator
    cat = _fk_catalog()
    if target in cat:
        _FK_CACHE[target] = cat[target]
        return cat[target]
    # 2) fallback: live sys.foreign_keys (name-join filtered)
    if "." in target:
        schema, tbl = target.split(".", 1)
    else:
        schema, tbl = "dbo", target
    sql = _t("""
        SELECT fk.name AS fk_name, c.name AS col,
               SCHEMA_NAME(rt.schema_id)+'.'+rt.name AS ref_table, rc.name AS ref_col
        FROM   sys.foreign_keys fk
        JOIN   sys.tables  pt ON pt.object_id = fk.parent_object_id
        JOIN   sys.schemas ps ON ps.schema_id = pt.schema_id
        JOIN   sys.foreign_key_columns kc ON kc.constraint_object_id = fk.object_id
        JOIN   sys.columns c  ON c.object_id  = fk.parent_object_id     AND c.column_id  = kc.parent_column_id
        JOIN   sys.tables  rt ON rt.object_id = fk.referenced_object_id
        JOIN   sys.columns rc ON rc.object_id = fk.referenced_object_id AND rc.column_id = kc.referenced_column_id
        WHERE  ps.name = :schema AND pt.name = :tbl
        ORDER  BY fk.name
    """)
    grouped: dict = {}
    with engine.connect() as con:
        for r in con.execute(sql, {"schema": schema, "tbl": tbl}):
            g = grouped.setdefault(r.fk_name, {"ref": r.ref_table, "cols": []})
            g["cols"].append((r.col, r.ref_col))
    out = [FKRef(n, d["ref"], d["cols"]) for n, d in grouped.items()]
    _FK_CACHE[target] = out
    return out


def _required_cols(engine, table):
    """Columns that MUST be supplied on insert (NOT NULL, no default, not
    identity/computed). Used to decide whether a key-only seed is safe."""
    if table in _REQ_CACHE:
        return _REQ_CACHE[table]
    if "." in table:
        schema, tbl = table.split(".", 1)
    else:
        schema, tbl = "dbo", table
    sql = _t("""
        SELECT c.name AS name
        FROM   sys.columns c
        JOIN   sys.tables  t ON t.object_id = c.object_id
        JOIN   sys.schemas s ON s.schema_id = t.schema_id
        LEFT JOIN sys.default_constraints dc
               ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
        WHERE  s.name = :schema AND t.name = :tbl
          AND  c.is_nullable = 0 AND c.is_identity = 0 AND c.is_computed = 0
          AND  dc.object_id IS NULL
    """)
    with engine.connect() as con:
        req = {r.name.lower() for r in con.execute(sql, {"schema": schema, "tbl": tbl})}
    _REQ_CACHE[table] = req
    return req


# Known audit/standard columns we can safely fill when a reference/entity table
# requires them but provides no default. Values are raw SQL expressions.
_AUDIT_DEFAULTS = {
    "active_ind":       "'Y'",
    "row_created_by":   "'DV_TABLE_LOADER'",
    "row_created_date": "GETDATE()",
    "row_changed_by":   "'DV_TABLE_LOADER'",
    "row_changed_date": "GETDATE()",
}


def _seed_fill(engine, table, key_cols):
    """For a table we're about to seed, figure out the required columns beyond
    the key(s) and how to fill them. Returns (extra_cols, extra_val_sql, None)
    on success, or ([], [], bad_col) if a required column has no known default
    (so the caller halts and audits). Columns with their own DB default or that
    are nullable need no action — _required_cols already excludes them."""
    req = _required_cols(engine, table)                 # lowercased, NOT NULL & no default
    keyset = {k.lower() for k in key_cols}
    extra_cols, extra_vals = [], []
    for c in sorted(req):
        if c in keyset:
            continue
        if c in _AUDIT_DEFAULTS:
            extra_cols.append(c)
            extra_vals.append(_AUDIT_DEFAULTS[c])
        else:
            return [], [], c                            # can't fill this one
    return extra_cols, extra_vals, None


# ── staging ──────────────────────────────────────────────────────────────────
def _ensure_fast_executemany(engine):
    """Turn on pyodbc fast_executemany for this engine (once) — the fallback
    path when BCP isn't available. Harmless on non-pyodbc engines."""
    if getattr(engine, "_dvtl_fem", False):
        return
    try:
        @event.listens_for(engine, "before_cursor_execute")
        def _set_fem(conn, cursor, statement, params, context, executemany):
            if executemany:
                try:
                    cursor.fast_executemany = True
                except Exception:
                    pass
        engine._dvtl_fem = True
    except Exception:
        pass


def _import_bcp():
    """Find the proven bcp_transport module wherever it's deployed."""
    for mod in ("bcp_transport", "loaders.core.bcp_transport",
                "modules.bcp_transport", "loaders.bcp_transport"):
        try:
            return __import__(mod, fromlist=["bcp_in"])
        except Exception:
            continue
    return None


def _to_sql_stage(engine, df, schema):
    _ensure_fast_executemany(engine)
    name = "stg_" + uuid.uuid4().hex[:12]
    df.to_sql(name, con=engine, schema=schema, if_exists="replace",
              index=False, chunksize=1000)
    return f"{schema}.{name}"


def _stage_bcp(engine, df, schema, bcp):
    """Stage via BCP: create an all-text staging table (staging is already text
    since _read_csv uses dtype=str), write a pipe-delimited file with the proven
    writer, and bcp it in. Returns the staging table FQN."""
    name = "stg_" + uuid.uuid4().hex[:12]
    full = f"{schema}.{name}"
    cols = list(df.columns)
    ddl = ", ".join(f"[{c}] nvarchar(max) NULL" for c in cols)
    with engine.begin() as con:
        con.execute(_t(f"CREATE TABLE {full} ({ddl})"))
    try:
        with engine.connect() as con:
            server = con.execute(_t(
                "SELECT CONVERT(nvarchar(256), SERVERPROPERTY('ServerName'))")).scalar()
            database = con.execute(_t("SELECT DB_NAME()")).scalar()
        sd = bcp.get_staging_dir()
        csv_path = sd / f"{name}.csv"
        w = bcp.BcpCsvWriter(csv_path)
        for row in df.itertuples(index=False, name=None):
            w.write_row(row)
        w.close()
        try:
            bcp.bcp_in(csv_path, full, str(server), str(database))
        finally:
            bcp.cleanup_staging(csv_path)
        return full
    except Exception:
        _drop(engine, full)          # remove the empty staging table on failure
        raise


def _date_columns(engine, table):
    """Names of date/time-typed columns in a target table — these need their
    text values normalized to ISO before the staging INSERT implicit-converts."""
    schema, tbl = table.split(".", 1) if "." in table else ("dbo", table)
    sql = _t("""
        SELECT c.name
        FROM   sys.columns c
        JOIN   sys.tables  t  ON t.object_id    = c.object_id
        JOIN   sys.schemas s  ON s.schema_id     = t.schema_id
        JOIN   sys.types   ty ON ty.user_type_id = c.user_type_id
        WHERE  s.name = :s AND t.name = :t
          AND  ty.name IN ('date','datetime','datetime2','smalldatetime',
                           'datetimeoffset')
    """)
    try:
        with engine.connect() as con:
            return {r[0] for r in con.execute(sql, {"s": schema, "t": tbl})}
    except Exception:
        return set()


def _stage(engine, df, schema="dataview", log=None):
    """Stage a frame for the load. Prefers BCP (fast bulk load via bcp_transport);
    falls back to fast_executemany to_sql if BCP is unavailable, the frame is
    empty, or BCP fails for any reason."""
    bcp = _import_bcp()
    if bcp is not None and len(df) > 0:
        try:
            t0 = time.time()
            full = _stage_bcp(engine, df, schema, bcp)
            if log:
                log(f"  staged {len(df)} rows via BCP in {time.time() - t0:.2f}s")
            return full
        except Exception as e:
            if log:
                log(f"  BCP staging failed ({type(e).__name__}); using to_sql. "
                    f"{str(e)[:200]}")
    return _to_sql_stage(engine, df, schema)


def _drop(engine, stg):
    try:
        with engine.begin() as con:
            con.execute(_t(f"DROP TABLE {stg}"))
    except Exception:
        pass


# ── the resolver + load ──────────────────────────────────────────────────────
def load_table(engine, csv_path, spec, *, apply=False, log=print):
    df = _read_csv(csv_path)

    # project + constants + uwi
    keep = {s: t for s, t in spec.columns.items() if s in df.columns}
    out = df[list(keep)].rename(columns=keep)
    for col, val in spec.constants.items():
        out[col] = val
    for c in spec.uwi_cols:
        if c in out.columns:
            out[c] = out[c].map(_norm_uwi)

    insert_cols = list(dict.fromkeys(list(keep.values()) + list(spec.constants.keys())))

    # generated sequence columns (seq_within): number rows 1..N within their
    # natural-key group, in file order. Gives a required id that has no source
    # column (e.g. curve_id within a log, station_id within a survey) a
    # deterministic value so the row satisfies its primary key.
    for seq_col in getattr(spec, "sequences", []) or []:
        part = [k for k in spec.natural_key if k != seq_col and k in out.columns]
        if part:
            out[seq_col] = out.groupby(part, sort=False).cumcount() + 1
        else:
            out[seq_col] = range(1, len(out) + 1)
        out[seq_col] = out[seq_col].astype(str)
        if seq_col not in insert_cols:
            insert_cols.append(seq_col)
        log(f"  seq_within: generated {seq_col} (1..N within "
            f"{', '.join(part) if part else 'file'})")

    # ── resolve FKs against policy ───────────────────────────────────────────
    seed_entity = []   # (ref_table, id_ref_col, name_col_in_entity, helper, id_col)
    seed_code   = []   # (ref_table, local_col)
    strict      = []   # FKRef (existence audit; composite-aware)
    reconcile   = []   # FKRef (controlled-vocab code tables — value reconciliation)
    deferred    = set()
    plan        = []   # (col(s), ref_table, strategy) for the log

    _fks = discover_fks(engine, spec.target)
    _src = "catalog" if spec.target in _fk_catalog() else "live"
    log(f"  [v3] {len(_fks)} FK(s) discovered on {spec.target} ({_src})")
    for fk in _fks:
        n_plan = len(plan)
        strat, params = _policy_for(fk.ref_table, spec)
        cols = ", ".join(lc for lc, _ in fk.cols)
        if strat == "SEED_ENTITY":
            for lc, rc in fk.cols:
                src = spec.seed_from.get(lc)
                if src and src in df.columns:
                    out[lc] = df[src].map(_sha1_id)
                    out[_seed_col(lc)] = df[src]
                    if lc not in insert_cols:
                        insert_cols.append(lc)
                    seed_entity.append((fk.ref_table, rc, params.get("name_col"),
                                        _seed_col(lc), lc))
                    plan.append((lc, fk.ref_table, "SEED_ENTITY"))
                # not provided -> NULL, no action
        elif strat == "SEED_CODE":
            for lc, rc in fk.cols:
                if lc in out.columns:
                    seed_code.append((fk.ref_table, lc, rc))
                    plan.append((lc, fk.ref_table, "SEED_CODE"))
        elif strat == "CONFORM":
            for lc, rc in fk.cols:
                cw = spec.conform.get(lc)
                if cw and lc in out.columns:
                    out[lc] = out[lc].map(lambda v: cw.get(v, v))
            if all(lc in out.columns for lc, _ in fk.cols):
                strict.append(fk)
                plan.append((cols, fk.ref_table, "CONFORM"))
        elif strat == "STRICT":
            if all(lc in out.columns for lc, _ in fk.cols):
                code_tbl = REF_TABLE_PATTERN.lower() in fk.ref_table.split(".")[-1].lower()
                if _fkr is not None and code_tbl and len(fk.cols) == 1:
                    reconcile.append(fk)
                    plan.append((cols, fk.ref_table, "STRICT·RECONCILE"))
                else:
                    strict.append(fk)
                    plan.append((cols, fk.ref_table, "STRICT"))
        elif strat == "DEFER":
            for lc, _ in fk.cols:
                if lc in out.columns:
                    deferred.add(lc)
                    plan.append((lc, fk.ref_table, "DEFER"))

        # nothing was done for this FK -> its column(s) aren't populated by the
        # mapping. Surface it (instead of hiding it) so a column that the table
        # actually needs doesn't silently slip through to an INSERT-time FK error.
        if len(plan) == n_plan:
            present = [lc for lc, _ in fk.cols if lc in out.columns]
            reason = ("not mapped — column absent from staged data"
                      if not present else f"{strat}: no value to act on")
            plan.append((cols, fk.ref_table, f"SKIP · {reason}"))

    # logical strict parents not enforced by a DB FK
    for lc, rt, rc in spec.parents:
        strict.append(FKRef("(logical)", rt, [(lc, rc)]))
        plan.append((lc, rt, "STRICT(parent)"))

    # DEFER wins: never insert a deferred column (but never drop a key column)
    for k in spec.natural_key:
        if k in deferred:
            log(f"[warn] {csv_path}: natural-key column '{k}' is DEFER — keeping it")
            deferred.discard(k)
    insert_cols = [c for c in insert_cols if c not in deferred]

    # every natural-key column must actually be present in the staged data, or
    # the dedup/insert can't run. Fail with a clear message instead of letting
    # SQL Server throw "Invalid column name" on the staging table.
    missing_key = [k for k in spec.natural_key if k not in out.columns]
    if missing_key:
        raise ValueError(
            f"{spec.target}: natural-key column(s) {missing_key} aren't populated "
            f"by this mapping, so rows can't be de-duplicated or inserted. Map a "
            f"source column (or constant) to them — or, if one is a required "
            f"foreign key seeded from a name (e.g. strat_unit_id from the "
            f"formation name), map that name column to it. "
            f"Staged columns: {sorted(out.columns)}")

    if not apply:
        for c, rt, st in plan:
            log(f"    fk {c:<22} -> {rt:<34} [{st}]")

    # normalize date/time columns to ISO (YYYY-MM-DD HH:MM:SS) before staging.
    # staging is all-text and the INSERT relies on implicit string->date
    # conversion, which fails on dashed DD-MM-YYYY/MM-DD-YYYY; ISO is
    # unambiguous. Unparseable values become NULL (and are counted in the log).
    date_cols = _date_columns(engine, spec.target)
    for c in [col for col in out.columns if col in date_cols]:
        raw = out[c].astype(str)
        nonempty = raw.str.strip().ne("")
        parsed = pd.to_datetime(out[c], errors="coerce", dayfirst=False,
                                format="mixed")
        bad = int((nonempty & parsed.isna()).sum())
        iso = parsed.dt.strftime("%Y-%m-%d %H:%M:%S")
        out[c] = iso.where(parsed.notna(), None)
        if bad:
            log(f"  date: {c} — {bad} value(s) couldn't be parsed, set to NULL "
                f"(check the source date format)")

    rows = len(out)
    stg = _stage(engine, out, log=log)
    result = {"file": csv_path, "target": spec.target, "rows": rows,
              "seeded": {}, "unmatched": {}, "inserted": 0, "skipped": 0,
              "fk_specs": [], "needs_reconcile": []}
    try:
        # ── FK value reconciliation (controlled-vocab code tables) ────────────
        # Build one spec per reconcilable FK from the staged distinct values, then
        # detect anything that isn't a valid code and has no saved decision. Those
        # HALT the load (plan or apply) and feed the reconciliation grid; nothing
        # is auto-admitted.
        reconcile_specs = []
        for fk in reconcile:
            lc, rc = fk.cols[0]
            vals = sorted({str(v) for v in out[lc].dropna().tolist() if str(v).strip()})
            reconcile_specs.append({"constraint": fk.name, "ref_table": fk.ref_table,
                                    "ref_col": rc, "fk_column": lc, "source_values": vals})
        result["fk_specs"] = reconcile_specs
        if reconcile_specs and _fkr is not None:
            recon = _fkr.collect_violations(engine, reconcile_specs)
            result["reconcile"] = recon
            if recon["violations"]:
                result["needs_reconcile"] = recon["violations"]
                by_field = {}
                for v in recon["violations"]:
                    by_field.setdefault(v["field"], []).append(v["source_value"])
                log(f"[RECONCILE] {csv_path}: {len(recon['violations'])} FK value(s) "
                    f"need a decision — "
                    + "; ".join(f"{k}: {', '.join(vs)}" for k, vs in by_field.items())
                    + "  → open the reconciliation grid, then re-run.")
                return result

        # STRICT / CONFORM existence audits — halt on any miss
        for fk in strict:
            conds = " AND ".join(f"t.[{rc}] = s.[{lc}]" for lc, rc in fk.cols)
            notnull = " AND ".join(f"s.[{lc}] IS NOT NULL AND s.[{lc}] <> ''"
                                   for lc, _ in fk.cols)
            with engine.connect() as con:
                miss = con.execute(_t(f"""
                    SELECT COUNT(*) FROM {stg} s
                    WHERE {notnull}
                      AND NOT EXISTS (SELECT 1 FROM {fk.ref_table} t WHERE {conds})
                """)).scalar()
            if miss:
                key = ",".join(lc for lc, _ in fk.cols) + "->" + fk.ref_table
                result["unmatched"][key] = int(miss)
        if result["unmatched"]:
            log(f"[HALT] {csv_path}: {result['unmatched']} unmatched key(s) — "
                f"audit before loading; nothing nulled or inserted.")
            return result

        key_join = " AND ".join(f"t.[{k}] = s.[{k}]" for k in spec.natural_key)

        if apply:
            # pre-flight: confirm every seed target is fillable BEFORE writing
            # anything, so an unfillable table halts with no partial commit.
            for ref_tbl, id_rc, name_col, helper, id_col in seed_entity:
                if not name_col:
                    result["unmatched"][f"seed {ref_tbl}"] = "no name column"
                    continue
                _, _, bad = _seed_fill(engine, ref_tbl, {id_rc, name_col})
                if bad:
                    result["unmatched"][f"seed {ref_tbl}"] = f"required col '{bad}' has no default"
            for ref_tbl, lc, rc in seed_code:
                _, _, bad = _seed_fill(engine, ref_tbl, {rc})
                if bad:
                    result["unmatched"][f"seed {ref_tbl}"] = f"required col '{bad}' has no default"
            if result["unmatched"]:
                log(f"[HALT] {csv_path}: can't auto-seed {result['unmatched']} — "
                    f"send me that table's DDL or supply a code mapping.")
                return result

            with engine.begin() as con:
                # apply saved FK value decisions: REMAP/NULL as staging UPDATEs,
                # and seed the steward-approved ADD codes (only those).
                for fk in reconcile:
                    lc, rc = fk.cols[0]
                    res = _fkr.get_resolutions(con.engine, fk.ref_table)
                    add_vals = _fkr.apply_to_stage(con, stg, lc, res)
                    if add_vals:
                        ex_cols, ex_vals, _ = _seed_fill(con.engine, fk.ref_table, {rc})
                        cols_sql = ", ".join([f"[{rc}]"] + [f"[{c}]" for c in ex_cols])
                        vals_sql = ", ".join([f"s.[{lc}]"] + ex_vals)
                        ph = ", ".join(f":a{i}" for i in range(len(add_vals)))
                        n = con.execute(_t(f"""
                            INSERT INTO {fk.ref_table} ({cols_sql})
                            SELECT DISTINCT {vals_sql} FROM {stg} s
                            WHERE s.[{lc}] IN ({ph})
                              AND NOT EXISTS (SELECT 1 FROM {fk.ref_table} e WHERE e.[{rc}] = s.[{lc}])
                        """), {f"a{i}": v for i, v in enumerate(add_vals)}).rowcount
                        result["seeded"][fk.ref_table] = \
                            result["seeded"].get(fk.ref_table, 0) + max(n, 0)
                # SEED_ENTITY — id + name (+ any required audit cols)
                for ref_tbl, id_rc, name_col, helper, id_col in seed_entity:
                    ex_cols, ex_vals, _ = _seed_fill(con.engine, ref_tbl,
                                                     {id_rc, name_col})
                    cols_sql = ", ".join([f"[{id_rc}]", f"[{name_col}]"]
                                         + [f"[{c}]" for c in ex_cols])
                    vals_sql = ", ".join([f"s.[{id_col}]", f"s.[{helper}]"] + ex_vals)
                    n = con.execute(_t(f"""
                        INSERT INTO {ref_tbl} ({cols_sql})
                        SELECT DISTINCT {vals_sql}
                        FROM {stg} s
                        WHERE s.[{id_col}] IS NOT NULL
                          AND NOT EXISTS (SELECT 1 FROM {ref_tbl} e WHERE e.[{id_rc}] = s.[{id_col}])
                    """)).rowcount
                    result["seeded"][ref_tbl] = max(n, 0)
                # SEED_CODE — distinct codes into the key col (+ required audit cols)
                for ref_tbl, lc, rc in seed_code:
                    ex_cols, ex_vals, _ = _seed_fill(con.engine, ref_tbl, {rc})
                    cols_sql = ", ".join([f"[{rc}]"] + [f"[{c}]" for c in ex_cols])
                    vals_sql = ", ".join([f"s.[{lc}]"] + ex_vals)
                    n = con.execute(_t(f"""
                        INSERT INTO {ref_tbl} ({cols_sql})
                        SELECT DISTINCT {vals_sql} FROM {stg} s
                        WHERE s.[{lc}] IS NOT NULL AND s.[{lc}] <> ''
                          AND NOT EXISTS (SELECT 1 FROM {ref_tbl} e WHERE e.[{rc}] = s.[{lc}])
                    """)).rowcount
                    result["seeded"][ref_tbl] = max(n, 0)

        col_list = ", ".join(f"[{c}]" for c in insert_cols)
        with engine.connect() as con:
            would = con.execute(_t(f"""
                SELECT COUNT(*) FROM {stg} s
                WHERE NOT EXISTS (SELECT 1 FROM {spec.target} t WHERE {key_join})
            """)).scalar()
        result["inserted"] = int(would or 0)
        result["skipped"] = rows - result["inserted"]

        if apply:
            with engine.begin() as con:
                con.execute(_t(f"""
                    INSERT INTO {spec.target} ({col_list})
                    SELECT {col_list} FROM {stg} s
                    WHERE NOT EXISTS (SELECT 1 FROM {spec.target} t WHERE {key_join})
                """))
            log(f"[load] {csv_path} -> {spec.target}: +{result['inserted']} "
                f"(skip {result['skipped']}) seeded {result['seeded']}")
        else:
            log(f"[plan] {csv_path} -> {spec.target}: would insert "
                f"{result['inserted']} (skip {result['skipped']})")
    finally:
        _drop(engine, stg)
    return result


def load_catalog_csvs(engine, paths, *, apply=False, log=print):
    import os
    jobs = []
    for p in paths:
        if not os.path.exists(p):
            log(f"[skip] {p}: file not found on disk (stale catalog entry)")
            continue
        key = recognize(p)
        if not key:
            log(f"[skip] {p}: no registry entry")
            continue
        jobs.append((p, REGISTRY[key]))
    jobs.sort(key=lambda j: len(j[1].parents))   # parents (no logical-parent) first
    return [load_table(engine, p, spec, apply=apply, log=log) for p, spec in jobs]
