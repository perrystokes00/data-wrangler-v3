"""
mapping_studio.py — foundation for the Mapping Studio.

Turns the hand-written loader REGISTRY into DATA produced by a mapping UI:

    domain -> table types -> per-table column mapping (auto-matched) -> snapshot

This module is the engine under that page. It provides:

  • the mapping store           dv_table_mapping + dv_table_mapping_col
  • the type-signature catalog  what column-sets identify each table type
                                (drives BOTH directory classification and the
                                 auto-match seed)
  • the auto-match engine       source<->target column alignment by
                                exact -> synonym -> fuzzy, with confidence
  • the classifier              score a file's header against signatures to
                                propose its table type + target table
  • target introspection        live target columns + which are required /
                                derived (NOT NULL, no default, no source)

Pure functions (auto_match, classify, _canon) carry no DB dependency and are
unit-testable; the store + introspection functions take a SQLAlchemy engine.
Bare-14 UWI and the SHA-1 / FK-policy conventions are unchanged — this only
decides the column map; the existing loader machinery does the load.
"""
from __future__ import annotations

import difflib
import json
import time

from sqlalchemy import text as _t


# ── synonym vocabulary (domain knowledge; canonical -> aliases) ──────────────
# Auto-match treats any alias as its canonical form, so INCLINATION and incl
# match, SRVY_ID and survey_id match, TVDSS and tvd match, etc.
SYNONYMS = {
    "uwi":               ["uwi", "uwi14", "api", "api14", "api_no", "well_id"],
    "well_name":         ["well_name", "wellname", "well", "name"],
    "survey_id":         ["survey_id", "srvy_id", "survey", "srvy"],
    "station_id":        ["station_id", "sta_id", "station", "survey_seq_no",
                          "station_seq_no", "station_seq", "seq_no", "station_no"],
    "md":                ["md", "measured_depth", "mdepth", "depth_md"],
    "incl":              ["incl", "inclination", "inc", "deviation", "dev"],
    "azim":              ["azim", "azimuth", "azi", "azm"],
    "tvd":               ["tvd", "tvdss", "tvd_ss", "true_vertical_depth"],
    "tvd_top":           ["tvd_top", "tvdss_top", "tvd_formation_top"],
    "ns_offset":         ["ns_offset", "north_south", "ns", "northing"],
    "ew_offset":         ["ew_offset", "east_west", "ew", "easting"],
    "surface_latitude":  ["surface_latitude", "latitude", "lat", "surf_lat"],
    "surface_longitude": ["surface_longitude", "longitude", "lon", "long", "surf_lon"],
    "dls":               ["dls", "dogleg", "dogleg_severity"],
    "source":            ["source", "data_source", "src"],
    "operator_name":     ["operator", "operator_name", "oper"],
    "field_name":        ["field", "field_name"],
    "well_type":         ["well_type", "well_class", "class", "type"],
    "well_status":       ["well_status", "status"],
    "depth_datum":       ["depth_datum", "datum"],
    "strat_unit_name":   ["strat_unit_name", "formation", "formation_name", "pick", "marker"],
    "strat_name_set":    ["strat_name_set", "strat_name_set_id", "name_set", "name_set_id"],
    "interp_id":         ["interp_id", "interpretation_id", "interp"],
    "interp_date":       ["interp_date", "interpretation_date", "pick_date"],
    "interp_by":         ["interp_by", "interpreted_by", "interpreter", "interp_author"],
    "strat_unit_type":   ["strat_unit_type", "strat_type", "stratigraphic_type"],
    "pick_location":     ["pick_location", "pick_loc", "boundary", "pick_position"],
    "top_depth":         ["top_depth", "top_md", "pick_depth", "depth"],
    "base_depth":        ["base_depth", "base_md", "bottom_depth", "bottom_md", "base_depth_md"],
    "curve_mnemonic":    ["curve_mnemonic", "mnemonic", "curve", "curve_name", "log_mnemonic"],
    "curve_unit":        ["curve_unit", "unit", "uom"],
    "curve_long_name":   ["curve_long_name", "description", "long_name", "curve_description"],
}
_ALIAS = {}
for _canon_name, _aliases in SYNONYMS.items():
    for _a in _aliases:
        if _a in _ALIAS and _ALIAS[_a] != _canon_name:
            raise ValueError(
                f"synonym alias '{_a}' is claimed by both '{_ALIAS[_a]}' and "
                f"'{_canon_name}' — aliases must be unique across canonical groups")
        _ALIAS[_a] = _canon_name


# ── configurable schema binding ──────────────────────────────────────────────
# The Studio's classifier scores files against the LIVE target columns, so it is
# schema-agnostic by construction — it just needs to know WHERE to look. These
# three settings supply that, and default to the original DataView layout for
# backward compatibility:
#   TARGET_SCHEMA / TARGET_PREFIX  the customer's data tables (introspected)
#   STORE_SCHEMA                   where the Studio's own bookkeeping lives
#                                  (dv_table_mapping / _col / signature / synonym)
# A customer install calls configure() once at startup (e.g. when the data model
# is selected) to point the Studio at a different schema. The store schema is
# kept separate from the data schema so the registry never pollutes the model.
TARGET_SCHEMA = "dataview"
TARGET_PREFIX = "dv_"
STORE_SCHEMA  = "dataview"
REF_TABLE_PATTERN = "dv_r_"     # substring identifying controlled-vocabulary
                                # code tables (these reconcile instead of halt)


def configure(*, target_schema=None, target_prefix=None, store_schema=None,
              ref_table_pattern=None):
    """Point the Studio at a customer's schema. Any arg left None is unchanged.
    Returns the resulting binding so callers can log/display it. Idempotent.
    The reference-table pattern is also pushed to dv_table_loader so its FK
    code-table detection (reconcile vs hard-halt) matches the customer's naming."""
    global TARGET_SCHEMA, TARGET_PREFIX, STORE_SCHEMA, REF_TABLE_PATTERN
    if target_schema is not None:
        TARGET_SCHEMA = str(target_schema).strip()
    if target_prefix is not None:
        TARGET_PREFIX = str(target_prefix).strip()
    if store_schema is not None:
        STORE_SCHEMA = str(store_schema).strip()
    if ref_table_pattern is not None:
        REF_TABLE_PATTERN = str(ref_table_pattern).strip()
    try:                                            # keep the loader in sync
        from dataview.mapping import dv_table_loader as _L
        _L.REF_TABLE_PATTERN = REF_TABLE_PATTERN
    except Exception:
        pass
    return {"target_schema": TARGET_SCHEMA, "target_prefix": TARGET_PREFIX,
            "store_schema": STORE_SCHEMA, "ref_table_pattern": REF_TABLE_PATTERN}


def _canon(col, alias_map=None):
    c = str(col).strip().lower()
    return (alias_map or _ALIAS).get(c, c)


def fingerprint(source_cols):
    """Stable signature of a source layout: SHA-1 of the sorted, normalized
    column names. Order-independent, so the same vendor format always yields the
    same fingerprint, and a different layout yields a different one. This is the
    snapshot key — 'new data in the same format' = same fingerprint = reload."""
    import hashlib
    norm = sorted({str(c).strip().lower() for c in source_cols if str(c).strip()})
    return hashlib.sha1("|".join(norm).encode("utf-8")).hexdigest()


# ── type-signature catalog ───────────────────────────────────────────────────
# must_have:     all must be present for the type to be a candidate
# must_not_have: presence disqualifies (separates look-alike types)
# signature_cols: contribute to the match score among candidates
# Seeded with the types we already know; extend as new types appear (later this
# moves into a table so adding "core"/"checkshot" is data, not code).
SIGNATURES = [
    {"table_type": "well_header", "domain": "Wells", "category": "Header",
     "target_table": "dataview.dv_well",
     "must_have": ["UWI", "WELL_NAME"],
     "must_not_have": ["SRVY_ID", "MD", "CURVE_MNEMONIC", "FORMATION"],
     "signature_cols": ["UWI", "WELL_NAME", "OPERATOR", "WELL_CLASS",
                        "STATUS", "SPUD_DATE", "FIELD_NAME"]},

    {"table_type": "well_dir_survey_hdr", "domain": "Wells", "category": "Directional Survey",
     "target_table": "dataview.dv_well_dir_srvy_hdr",
     "must_have": ["UWI", "SRVY_ID"],
     "must_not_have": ["MD", "INCLINATION", "AZIMUTH", "TVDSS"],
     "signature_cols": ["UWI", "SRVY_ID", "SURVEY_SEQ_NO", "SOURCE"]},

    {"table_type": "well_dir_survey_data", "domain": "Wells", "category": "Directional Survey",
     "target_table": "dataview.dv_well_dir_srvy_sta",
     "must_have": ["UWI", "SRVY_ID", "MD"],
     "must_not_have": [],
     "signature_cols": ["MD", "INCLINATION", "AZIMUTH", "TVDSS"]},

    {"table_type": "well_picks", "domain": "Wells", "category": "Tops / Picks",
     "target_table": "dataview.dv_well_formation_top",
     "must_have": ["UWI", "FORMATION"],
     "must_not_have": ["SRVY_ID", "CURVE_MNEMONIC", "MNEMONIC",
                       "CORE_NO", "CORE_ID", "SAMPLE_NO", "SAMPLE_NUMBER",
                       "POROSITY", "PERMEABILITY"],
     "signature_cols": ["UWI", "FORMATION", "MD", "TVD"]},

    {"table_type": "well_log_hdr", "domain": "Wells", "category": "Log Header",
     "target_table": "dataview.dv_well_log",
     "must_have": ["UWI", "LOG_NAME"],
     "must_not_have": ["MNEMONIC", "FORMATION", "SRVY_ID"],
     "signature_cols": ["UWI", "LOG_NAME", "LOG_TYPE", "RUN_NUMBER",
                        "TOP_DEPTH", "BASE_DEPTH", "SERVICE_COMPANY"]},

    {"table_type": "well_log_curve", "domain": "Wells", "category": "Log Curves",
     "target_table": "dataview.dv_well_log_curve",
     "must_have": ["UWI", "MNEMONIC"],
     "must_not_have": ["SRVY_ID", "FORMATION", "LOG_NAME"],
     "signature_cols": ["UWI", "MNEMONIC", "UNIT", "DESCRIPTION", "CURVE"]},
]

# ── full catalog of well data types (NOT limited to what's mapped) ───────────
# The complete vocabulary of well data types and the conventional target table
# each proposes. Types the studio can auto-detect (the SIGNATURES above) are a
# subset; the rest you declare and the studio proposes the table (marked 'new'
# if it doesn't exist yet). Data, not code — extend freely; add Seismic later.
DATA_TYPE_CATALOG = {
    "Wells": [
        ("Header",                  ["dataview.dv_well"]),
        ("Directional Survey",      ["dataview.dv_well_dir_srvy_hdr",
                                     "dataview.dv_well_dir_srvy_sta"]),
        ("Tops / Picks",            ["dataview.dv_well_formation_top"]),
        ("Log Header",              ["dataview.dv_well_log"]),
        ("Log Curves",              ["dataview.dv_well_log_curve"]),
        ("Core",                    ["dataview.dv_well_core"]),
        ("DST / Well Test",         ["dataview.dv_well_test"]),
        ("Production",              ["dataview.dv_well_production"]),
        ("Checkshot / Time-Depth",  ["dataview.dv_well_checkshot"]),
        ("Perforation",             ["dataview.dv_well_perforation"]),
        ("Completion",              ["dataview.dv_well_completion"]),
        ("Casing / Tubular",        ["dataview.dv_well_casing"]),
        ("Pressure",                ["dataview.dv_well_pressure"]),
        ("Fluid Sample / PVT",      ["dataview.dv_well_fluid_sample"]),
        ("Mud Log",                 ["dataview.dv_well_mud_log"]),
        ("Zone / Interval",         ["dataview.dv_well_zone"]),
        ("Status History",          ["dataview.dv_well_status"]),
        ("License / Permit",        ["dataview.dv_well_license"]),
        ("Remarks / Notes",         ["dataview.dv_well_remark"]),
    ],
}

# target table -> data type (covers every catalog target, not just detected ones)
_TARGET_CATEGORY = {tbl: typ
                    for entries in DATA_TYPE_CATALOG.values()
                    for typ, tbls in entries for tbl in tbls}
_TARGET_DOMAIN = {tbl: dom
                  for dom, entries in DATA_TYPE_CATALOG.items()
                  for _typ, tbls in entries for tbl in tbls}
_TYPE_CATEGORY = {s["table_type"]: s.get("category", "Other") for s in SIGNATURES}


def category_of_type(table_type):
    return _TYPE_CATEGORY.get(table_type, "Other")


def category_of_target(target_table):
    return _TARGET_CATEGORY.get(target_table, "Other")


def derive_table_type(target_table):
    """A readable type label for any target table. Prefers a curated label (from
    the seed catalog / signatures) when the table is known; otherwise derives one
    from the table name (strip schema + the configured TARGET_PREFIX, prettify).
    This is what lets the confirm grid show a sensible Type for a customer's
    tables that were never seeded — the engine classifies by live columns, this
    just labels the result."""
    tl = str(target_table).lower()
    # 1. curated catalog label ("Core", "DST / Well Test", …) when known
    for _dom, entries in DATA_TYPE_CATALOG.items():
        for typ, tbls in entries:
            if any(str(t).lower() == tl for t in tbls):
                return typ
    # 2. signature label
    for s in SIGNATURES:
        if s["target_table"].lower() == tl:
            return s["table_type"]
    # 3. derive from the table name
    name = str(target_table).split(".")[-1]
    p = (TARGET_PREFIX or "").lower()
    if p and name.lower().startswith(p):
        name = name[len(p):]
    pretty = name.replace("_", " ").strip().title()
    return pretty or str(target_table).split(".")[-1]


# transforms available for mapped/derived columns (data; extend freely)
TRANSFORMS = ["", "norm_uwi14", "seq_within(survey_id)", "seq_within(log_id)",
              "seq_within(uwi)", "upper", "trim", "to_date"]


def propose_transform(target_column, has_source):
    """Sensible default transform for a column. uwi -> bare-14 normalization;
    a required *_id with no source -> sequence within its parent (e.g.
    station_id within a survey, curve_id within a log)."""
    t = target_column.strip().lower()
    if t == "uwi":
        return "norm_uwi14"
    if not has_source:
        if t == "station_id":
            return "seq_within(survey_id)"
        if t == "curve_id":
            return "seq_within(log_id)"
    return ""


def data_types(engine, domain="Wells"):
    """The list of data types for the confirm-grid dropdowns, each with its
    target table(s) and an existence flag. Sources:
      • the seeded DATA_TYPE_CATALOG (curated labels for known tables), and
      • every LIVE target table not already covered, labelled by derive_table_type
    so a customer's own schema populates the dropdown with no authoring.
    On a customer schema (none of the seed tables exist) the non-existent seed
    entries are suppressed, so the grid only offers real tables.
        [{"type": "Core", "targets": [{"table": "dataview.dv_well_core", "exists": False}]}]
    """
    try:
        existing = set(list_target_tables(engine))
    except Exception:
        existing = set()
    seed = DATA_TYPE_CATALOG.get(domain, [])
    seed_tables = {t for _, tbls in seed for t in tbls}
    native = any(t in existing for t in seed_tables)   # are we on the seeded schema?

    out, covered = [], set()
    for typ, tbls in seed:
        # on a foreign schema, drop seed targets that don't exist (your table
        # names shouldn't pollute a customer's dropdown); on the native schema
        # keep them so you can pre-pick a table you're about to create.
        tgts = [t for t in tbls if (native or t in existing)]
        if not tgts:
            continue
        out.append({"type": typ,
                    "targets": [{"table": t, "exists": t in existing} for t in tgts]})
        covered.update(tgts)
    # append any live target table not covered by a seed type, with a derived
    # label — this is what makes an arbitrary customer schema usable
    for t in sorted(existing - covered):
        out.append({"type": derive_table_type(t),
                    "targets": [{"table": t, "exists": True}]})
    return out


# ── filename keyword hints (secondary signal; columns stay primary) ──────────
# table_type -> keywords. Types without a signature yet (checkshot, production)
# only surface as a clue on otherwise-unknown files. Data, not code — moves to a
# table later so adding "checkshot -> well_checkshot" is a one-line edit.
FILENAME_HINTS = {
    "well_header":          ["well_header", "wellheader", "well_master", "wellbore", "header"],
    "well_dir_survey_hdr":  ["survey_hdr", "dir_survey_hdr", "directional_hdr", "deviation_hdr"],
    "well_dir_survey_data": ["directional", "deviation", "dir_survey", "dev_survey", "survey"],
    "well_picks":           ["picks", "pick", "tops", "strat", "formation_top", "marker"],
    "well_log_hdr":         ["log_hdr", "log_header", "loghdr", "log_run", "log_master"],
    "well_log_curve":       ["log_curve", "logcurve", "curve", "las", "log"],
    "well_core":            ["core"],
    "well_dst":             ["dst", "drill_stem"],
    "well_checkshot":       ["checkshot", "check_shot"],     # future type (no table yet)
    "well_production":      ["production", "prod"],           # future type
}


def filename_clue(filename):
    """Return the table_type a filename hints at (by keyword), or None. Used to
    annotate unknowns — e.g. 'checkshot.csv' surfaces as a clue even though no
    target table exists for it yet."""
    fn = (filename or "").lower()
    for ttype, kws in FILENAME_HINTS.items():
        if any(k in fn for k in kws):
            return ttype
    return None


def classify(file_cols, filename=None, learned=None, schema=None, rarity=None,
             alias_map=None, schema_canon=None):
    """Rank candidate types for a file. Signals, strongest first:
      1. learned signature  — a confirmed fingerprint->type, definitive
      2. real schema columns — when `schema` is given, score the file against the
         ACTUAL target-table columns (introspection / JSON catalog), weighted by
         how discriminating each column is (porosity->core, azim->stations).
         No guessed column names.
      3. filename keywords   — secondary; breaks ties, rescues near-misses
    Falls back to the seeded SIGNATURES only when no schema is supplied.
    `schema` is {target_table: [columns]} from load_schema(); `rarity` from
    column_rarity() (computed if omitted)."""
    fset = {str(c).strip().lower() for c in file_cols}
    fname = (filename or "").lower()

    # 1. learned signature — confirmed truth for this exact layout
    if learned:
        hit = learned.get(fingerprint(file_cols))
        if hit:
            return [{"table_type": hit["table_type"], "target_table": hit["target_table"],
                     "domain": hit.get("domain"), "score": 1.0, "col_score": 1.0,
                     "filename_hit": False, "source": "learned"}]

    # 2. real-schema classification (preferred) — grounded in actual columns
    if schema:
        ranked = classify_by_schema(file_cols, schema, rarity, alias_map=alias_map,
                                    schema_canon=schema_canon)
        am = alias_map or _ALIAS
        fcanon = {_canon(c, am) for c in file_cols}
        sig_by_target = {s["target_table"]: s for s in SIGNATURES}
        out = []
        for r in ranked:
            tbl = r["target_table"]
            ttype = next((s["table_type"] for s in SIGNATURES if s["target_table"] == tbl), None) \
                    or derive_table_type(tbl)
            fn_hit = bool(ttype) and any(k in fname for k in FILENAME_HINTS.get(ttype, []))
            score = min(r["score"] + (0.10 if fn_hit else 0.0), 1.0)
            # signature consistency: the column-mass scorer can't tell apart
            # sibling tables that share keys (survey header vs stations). Demote a
            # table whose seeded signature is contradicted — the file is missing a
            # column the table REQUIRES (e.g. stations needs MD; a header file
            # lacks it) or carries one the table FORBIDS. Only applies to seeded
            # tables; customer tables without a signature are untouched.
            sig = sig_by_target.get(tbl)
            if sig:
                must_have = {_canon(c, am) for c in sig.get("must_have", [])}
                must_not = {_canon(c, am) for c in sig.get("must_not_have", [])}
                if (must_have - fcanon) or (must_not & fcanon):
                    score = round(score * 0.35, 3)
            out.append({"table_type": ttype, "target_table": tbl,
                        "domain": _TARGET_DOMAIN.get(tbl), "score": round(score, 3),
                        "col_score": r["score"], "filename_hit": fn_hit,
                        "source": "schema+filename" if fn_hit else "schema"})
        return sorted(out, key=lambda d: -d["score"])

    # 3. fallback: seeded SIGNATURES (only when schema unavailable)
    out = []
    for sig in SIGNATURES:
        if {c.lower() for c in sig.get("must_not_have", [])} & fset:
            continue
        must_ok = {c.lower() for c in sig["must_have"]}.issubset(fset)
        sc = {c.lower() for c in sig["signature_cols"]}
        col_score = len(sc & fset) / max(len(sc), 1)
        fn_hit = any(k in fname for k in FILENAME_HINTS.get(sig["table_type"], []))
        if must_ok:
            score = min(col_score + (0.15 if fn_hit else 0.0), 1.0)
        elif fn_hit:
            score = round(col_score * 0.5 + 0.30, 2)
        else:
            continue
        out.append({"table_type": sig["table_type"], "target_table": sig["target_table"],
                    "domain": sig["domain"], "score": round(score, 2),
                    "col_score": round(col_score, 2), "filename_hit": fn_hit,
                    "source": "column+filename" if fn_hit else "column"})
    return sorted(out, key=lambda d: -d["score"])


# ── schema-grounded classification (uses REAL target columns) ────────────────
def load_schema(engine, schema_name=None, prefix=None):
    """{target_table: [columns]} for all dv_* tables in ONE query (not one per
    table — that was the scan slowdown). Authoritative and current. Schema/prefix
    default to the configured TARGET binding (configure())."""
    schema_name = schema_name if schema_name is not None else TARGET_SCHEMA
    prefix = prefix if prefix is not None else TARGET_PREFIX
    sql = _t("""
        SELECT s.name + '.' + t.name AS tbl, c.name AS col
        FROM   sys.columns c
        JOIN   sys.tables  t ON t.object_id = c.object_id
        JOIN   sys.schemas s ON s.schema_id = t.schema_id
        WHERE  s.name = :s AND t.name LIKE :p
        ORDER  BY t.name, c.column_id
    """)
    out = {}
    try:
        with engine.connect() as con:
            for r in con.execute(sql, {"s": schema_name, "p": prefix + "%"}):
                out.setdefault(r.tbl, []).append(str(r.col).strip().lower())
    except Exception:
        return {}
    return out


def column_rarity(schema):
    """Per-column discriminating weight: a column in few tables (porosity, azim)
    is highly identifying; one in many (uwi, source, row_created_by) barely is.
    weight = ln(1 + n_tables / doc_freq)."""
    import math
    from collections import Counter
    dfreq = Counter()
    for cols in schema.values():
        for c in set(cols):
            dfreq[c] += 1
    n = max(len(schema), 1)
    return {c: math.log(1.0 + n / cnt) for c, cnt in dfreq.items()}


def classify_by_schema(file_cols, schema, rarity=None, *, alias_map=None, top=6,
                       schema_canon=None):
    """Score a file against every real target table by how well its columns map
    (through synonyms) onto that table's ACTUAL columns, weighted by how
    discriminating the matched columns are. Returns ranked
    [{target_table, score, covered, file_cov}].

    `schema_canon` (optional) = precomputed {table: set(canonical cols)} so a
    multi-file scan doesn't re-canonicalize the whole schema for every file."""
    if not schema:
        return []
    am = alias_map or _ALIAS
    rarity = rarity or column_rarity(schema)
    if schema_canon is None:
        schema_canon = {tbl: {_canon(c, am) for c in cols}
                        for tbl, cols in schema.items()}
    fcanon = {_canon(c, am) for c in file_cols}
    ranked = []
    for tbl, tcanon in schema_canon.items():
        hits = fcanon & tcanon
        if not hits:
            continue
        mass = sum(rarity.get(c, 1.0) for c in hits)            # discriminating mass
        file_cov = len(hits) / max(len(fcanon), 1)              # of the file explained
        ranked.append({"target_table": tbl, "mass": mass,
                       "covered": len(hits), "file_cov": round(file_cov, 2)})
    if ranked:
        mx = max(r["mass"] for r in ranked) or 1.0
        for r in ranked:
            r["score"] = round(0.7 * (r["mass"] / mx) + 0.3 * r["file_cov"], 3)
    return sorted(ranked, key=lambda d: -d["score"])[:top]


def build_schema_canon(schema, alias_map=None):
    """Precompute {table: set(canonical columns)} once for a scan."""
    am = alias_map or _ALIAS
    return {tbl: {_canon(c, am) for c in cols} for tbl, cols in (schema or {}).items()}


# ── auto-match engine ────────────────────────────────────────────────────────
def auto_match(source_cols, target_cols, *, required=None, alias_map=None,
               fuzzy_cutoff=0.82):
    """Align source columns to target columns: exact -> synonym -> fuzzy.

    Returns:
      matches            [{target, source, confidence, method}]  (source None if unmatched)
      unmatched_sources  source columns not assigned to any target
      derived_required   target columns that are REQUIRED but have no source
                         (these MUST be derived/constant — e.g. station_id)
    alias_map: learned synonyms (alias->canonical) merged over the seed; pass the
    result of load_alias_map() so matching improves as the library grows.
    required: set of required target column names; used to flag derived_required.
    Confidence: exact 1.0, synonym 0.95, fuzzy = ratio.
    """
    am = alias_map or _ALIAS
    required = {r.lower() for r in (required or [])}
    canon_src = {s: _canon(s, am) for s in source_cols}
    low_src = {s: s.strip().lower() for s in source_cols}
    used = set()
    pick = {}                                        # target -> (source, conf, method)

    # PASS 1 — exact (literal, case-insensitive). Claimed first so a source that
    # exactly matches a column is never stolen by an earlier synonym match.
    for t in target_cols:
        tl = t.strip().lower()
        for s in source_cols:
            if s not in used and low_src[s] == tl:
                pick[t] = (s, 1.0, "exact"); used.add(s); break

    # PASS 2 — synonym (canonical equality), among still-unused sources
    for t in target_cols:
        if t in pick:
            continue
        tn = _canon(t, am)
        for s in source_cols:
            if s not in used and canon_src[s] == tn:
                pick[t] = (s, 0.95, "synonym"); used.add(s); break

    # PASS 3 — fuzzy fallback
    for t in target_cols:
        if t in pick:
            continue
        cand = [s for s in source_cols if s not in used]
        m = difflib.get_close_matches(t.lower(), [low_src[s] for s in cand],
                                      n=1, cutoff=fuzzy_cutoff)
        if m:
            s = next(s for s in cand if low_src[s] == m[0])
            r = difflib.SequenceMatcher(None, low_src[s], t.lower()).ratio()
            pick[t] = (s, round(r, 2), "fuzzy"); used.add(s)

    matches = [{"target": t,
                "source": pick[t][0] if t in pick else None,
                "confidence": pick[t][1] if t in pick else 0.0,
                "method": pick[t][2] if t in pick else "none"}
               for t in target_cols]
    unmatched_sources = [s for s in source_cols if s not in used]
    derived_required = [m["target"] for m in matches
                        if m["source"] is None and m["target"].lower() in required]
    return {"matches": matches, "unmatched_sources": unmatched_sources,
            "derived_required": derived_required}


def primary_key(engine, table):
    """Primary-key column names for a table, in key order. [] if no PK."""
    schema, tbl = table.split(".", 1) if "." in table else ("dbo", table)
    sql = _t("""
        SELECT c.name
        FROM   sys.indexes i
        JOIN   sys.index_columns ic ON ic.object_id = i.object_id
                                   AND ic.index_id  = i.index_id
        JOIN   sys.columns c ON c.object_id = ic.object_id
                            AND c.column_id = ic.column_id
        JOIN   sys.tables  t ON t.object_id = i.object_id
        JOIN   sys.schemas s ON s.schema_id = t.schema_id
        WHERE  i.is_primary_key = 1 AND s.name = :s AND t.name = :t
        ORDER  BY ic.key_ordinal
    """)
    with engine.connect() as con:
        return [r[0] for r in con.execute(sql, {"s": schema, "t": tbl})]


def natural_key_for(engine, table, required):
    """The dedup key for a load: the table's real PRIMARY KEY (minus any
    identity column, which the DB generates), falling back to the required
    columns when there's no usable PK. Using the PK avoids pulling unrelated
    required columns (e.g. a required FK the file doesn't supply) into the key."""
    tcols = {c["name"]: c for c in target_columns(engine, table)}
    pk = [c for c in primary_key(engine, table)
          if c in tcols and not tcols[c]["identity"]]
    return pk or sorted(required)


# ── target introspection ─────────────────────────────────────────────────────
def target_columns(engine, table):
    """Live target columns with the metadata the studio needs:
    [{name, type, nullable, has_default, identity, required}] in ordinal order.
    'required' = NOT NULL and no default and not identity (must be supplied)."""
    schema, tbl = table.split(".", 1) if "." in table else ("dbo", table)
    sql = _t("""
        SELECT c.name, ty.name AS type, c.is_nullable, c.is_identity,
               c.is_computed,
               CASE WHEN dc.object_id IS NULL THEN 0 ELSE 1 END AS has_default
        FROM   sys.columns c
        JOIN   sys.tables  t  ON t.object_id = c.object_id
        JOIN   sys.schemas s  ON s.schema_id = t.schema_id
        JOIN   sys.types   ty ON ty.user_type_id = c.user_type_id
        LEFT JOIN sys.default_constraints dc
               ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
        WHERE  s.name = :s AND t.name = :t
        ORDER  BY c.column_id
    """)
    out = []
    with engine.connect() as con:
        for r in con.execute(sql, {"s": schema, "t": tbl}):
            # computed and identity columns are DB-generated: never mappable,
            # never required.
            generated = bool(r.is_identity) or bool(r.is_computed)
            req = ((not r.is_nullable) and (not r.has_default) and not generated)
            out.append({"name": r.name, "type": r.type, "nullable": bool(r.is_nullable),
                        "has_default": bool(r.has_default),
                        "identity": bool(r.is_identity),
                        "computed": bool(r.is_computed),
                        "required": req})
    return out


def list_target_tables(engine, schema=None, prefix=None):
    """All candidate target tables (for the confirm-grid target dropdown).
    Schema/prefix default to the configured TARGET binding (configure())."""
    schema = schema if schema is not None else TARGET_SCHEMA
    prefix = prefix if prefix is not None else TARGET_PREFIX
    with engine.connect() as con:
        rows = con.execute(_t("""
            SELECT s.name + '.' + t.name AS tbl
            FROM   sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id
            WHERE  s.name = :s AND t.name LIKE :p
            ORDER  BY t.name
        """), {"s": schema, "p": prefix + "%"}).fetchall()
    return [r.tbl for r in rows]


def available_types(engine, domain=None):
    """Curated types from SIGNATURES, filtered to those whose target table
    actually exists in the connected DB (and optional domain). This is the type
    dropdown — it never offers a type you can't load to, and a new type appears
    automatically once you add its table + signature."""
    try:
        existing = set(list_target_tables(engine))
    except Exception:
        existing = {s["target_table"] for s in SIGNATURES}
    out, seen = [], set()
    for s in SIGNATURES:
        if domain and s["domain"] != domain:
            continue
        if s["target_table"] not in existing:
            continue
        if s["table_type"] in seen:
            continue
        seen.add(s["table_type"])
        out.append({"table_type": s["table_type"], "target_table": s["target_table"],
                    "domain": s["domain"]})
    return out


def categories(engine, domain=None):
    """Data-type categories -> their existing target tables, for the dependent
    'data type' -> 'target table' dropdowns. Existence-filtered: a category only
    lists tables that exist in the connected DB, and a category with no existing
    tables is dropped entirely. Returns an ordered dict-like list:
        [{"category": "Directional Survey",
          "targets": ["dataview.dv_well_dir_srvy_hdr", "dataview.dv_well_dir_srvy_sta"]}]
    """
    try:
        existing = set(list_target_tables(engine))
    except Exception:
        existing = {s["target_table"] for s in SIGNATURES}
    order, by_cat = [], {}
    for s in SIGNATURES:
        if domain and s["domain"] != domain:
            continue
        if s["target_table"] not in existing:
            continue
        cat = s.get("category", "Other")
        if cat not in by_cat:
            by_cat[cat] = []
            order.append(cat)
        if s["target_table"] not in by_cat[cat]:
            by_cat[cat].append(s["target_table"])
    return [{"category": c, "targets": by_cat[c]} for c in order]


def learn_signature(engine, source_cols, table_type, target_table, *,
                    domain=None, label=None, resolved_by="STEWARD"):
    """Record 'this column layout = this type' so future scans auto-classify it.
    Written when a steward overrides a detected type (and on mapping save). The
    classifier reads these first — confirmed truth outranks seeded guesses."""
    ensure_store(engine)
    fp = fingerprint(source_cols)
    with engine.begin() as con:
        con.execute(_t(f"""
            MERGE {STORE_SCHEMA}.dv_table_signature AS t
            USING (SELECT :fp AS source_fingerprint) AS s
              ON (t.source_fingerprint = s.source_fingerprint)
            WHEN MATCHED THEN
                UPDATE SET table_type=:tt, target_table=:tg, domain=:d, label=:lbl,
                           hit_count = t.hit_count + 1
            WHEN NOT MATCHED THEN
                INSERT (source_fingerprint, table_type, target_table, domain, label, row_created_by)
                VALUES (:fp, :tt, :tg, :d, :lbl, :by);
        """), {"fp": fp, "tt": table_type, "tg": target_table, "d": domain,
               "lbl": label, "by": resolved_by})
    return fp


def load_learned_signatures(engine):
    """{fingerprint: {table_type, target_table, domain, hit_count}} for classify."""
    try:
        with engine.connect() as con:
            rows = con.execute(_t(f"""
                SELECT source_fingerprint, table_type, target_table, domain, hit_count
                FROM {STORE_SCHEMA}.dv_table_signature
            """)).fetchall()
        return {r.source_fingerprint: {"table_type": r.table_type,
                                       "target_table": r.target_table,
                                       "domain": r.domain, "hit_count": r.hit_count}
                for r in rows}
    except Exception:
        return {}


# ── mapping store ────────────────────────────────────────────────────────────
def _ddl():
    """Build the store DDL for the CURRENT STORE_SCHEMA (resolved at call time so
    configure() is honoured). Creates the store schema first if it doesn't exist,
    then the four bookkeeping tables. Idempotent."""
    return f"""
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name='{STORE_SCHEMA}')
    EXEC('CREATE SCHEMA [{STORE_SCHEMA}]');
IF NOT EXISTS (SELECT 1 FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id
              WHERE s.name='{STORE_SCHEMA}' AND t.name='dv_table_mapping')
CREATE TABLE {STORE_SCHEMA}.dv_table_mapping (
    mapping_id        int IDENTITY(1,1) PRIMARY KEY,
    source_fingerprint nvarchar(40) NOT NULL,      -- SHA-1 of the source layout
    version           int NOT NULL,
    is_active         bit NOT NULL CONSTRAINT DF_tmap_active2 DEFAULT 1,
    label             nvarchar(120) NULL,          -- vendor/format name, e.g. 'KGS survey export'
    table_type        nvarchar(64)  NOT NULL,
    domain            nvarchar(40)  NULL,
    target_table      nvarchar(128) NOT NULL,
    natural_key       nvarchar(400) NULL,
    source_columns    nvarchar(max) NULL,          -- JSON list, for near-match + display
    row_created_by    nvarchar(128) NULL,
    row_created_date  datetime2 NOT NULL CONSTRAINT DF_tmap_date2 DEFAULT (GETDATE()),
    CONSTRAINT UQ_dv_table_mapping_ver UNIQUE (source_fingerprint, version)
);
IF NOT EXISTS (SELECT 1 FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id
              WHERE s.name='{STORE_SCHEMA}' AND t.name='dv_table_mapping_col')
CREATE TABLE {STORE_SCHEMA}.dv_table_mapping_col (
    mapping_col_id int IDENTITY(1,1) PRIMARY KEY,
    mapping_id     int NOT NULL
        CONSTRAINT FK_tmapcol_map REFERENCES {STORE_SCHEMA}.dv_table_mapping(mapping_id),
    target_column  nvarchar(128) NOT NULL,
    source_column  nvarchar(128) NULL,            -- NULL => derived / constant
    is_key         bit NOT NULL CONSTRAINT DF_tmapcol_key DEFAULT 0,
    is_derived     bit NOT NULL CONSTRAINT DF_tmapcol_der DEFAULT 0,
    transform      nvarchar(128) NULL,            -- e.g. norm_uwi14, seq_within(survey_id)
    constant_value nvarchar(400) NULL,
    confidence     numeric(4,2)  NULL,
    method         nvarchar(16)  NULL,
    CONSTRAINT UQ_dv_table_mapping_col UNIQUE (mapping_id, target_column)
);
IF NOT EXISTS (SELECT 1 FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id
              WHERE s.name='{STORE_SCHEMA}' AND t.name='dv_column_synonym')
CREATE TABLE {STORE_SCHEMA}.dv_column_synonym (
    synonym_id     int IDENTITY(1,1) PRIMARY KEY,
    target_column  nvarchar(128) NOT NULL,        -- canonical target column name
    alias          nvarchar(128) NOT NULL,        -- a source column name seen for it
    scope          nvarchar(8)   NOT NULL CONSTRAINT DF_syn_scope DEFAULT 'global',  -- global | table
    target_table   nvarchar(128) NULL,            -- set when scope='table'
    confidence     numeric(4,2)  NULL,
    hit_count      int NOT NULL CONSTRAINT DF_syn_hits DEFAULT 1,
    row_created_by nvarchar(128) NULL,
    row_created_date datetime2 NOT NULL CONSTRAINT DF_syn_date DEFAULT (GETDATE()),
    CONSTRAINT UQ_dv_column_synonym UNIQUE (target_column, alias, scope, target_table)
);
IF NOT EXISTS (SELECT 1 FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id
              WHERE s.name='{STORE_SCHEMA}' AND t.name='dv_table_signature')
CREATE TABLE {STORE_SCHEMA}.dv_table_signature (
    signature_id   int IDENTITY(1,1) PRIMARY KEY,
    source_fingerprint nvarchar(40) NOT NULL,     -- SHA-1 of the source layout
    table_type     nvarchar(64)  NOT NULL,        -- the confirmed type for that layout
    target_table   nvarchar(128) NULL,
    domain         nvarchar(40)  NULL,
    label          nvarchar(120) NULL,
    hit_count      int NOT NULL CONSTRAINT DF_sig_hits DEFAULT 1,
    row_created_by nvarchar(128) NULL,
    row_created_date datetime2 NOT NULL CONSTRAINT DF_sig_date DEFAULT (GETDATE()),
    CONSTRAINT UQ_dv_table_signature UNIQUE (source_fingerprint)
);
"""


def ensure_store(engine):
    with engine.begin() as con:
        con.execute(_t(_ddl()))


# ── learned synonyms ─────────────────────────────────────────────────────────
def load_alias_map(engine, target_table=None):
    """Merge the seed synonym dict with the learned library (global + this
    table's scoped aliases) into one alias->canonical map. Higher hit_count wins
    on conflict. Falls back to the seed if the table isn't there yet."""
    am = dict(_ALIAS)
    try:
        with engine.connect() as con:
            rows = con.execute(_t(f"""
                SELECT target_column, alias, scope, target_table, hit_count
                FROM   {STORE_SCHEMA}.dv_column_synonym
                WHERE  scope='global' OR (scope='table' AND target_table=:tt)
                ORDER  BY hit_count ASC          -- table-scoped/high-hit applied last (win)
            """), {"tt": target_table}).fetchall()
        for r in rows:
            am[r.alias.strip().lower()] = r.target_column.strip().lower()
    except Exception:
        pass
    return am


def harvest_synonyms(engine, columns, target_table, *, resolved_by="STEWARD"):
    """Record confirmed source->target pairs into the library so future
    auto-matches improve. Only non-trivial pairs (source != target) are learned;
    each confirmation bumps hit_count."""
    with engine.begin() as con:
        for c in columns:
            sc, tc = c.get("source_column"), c.get("target_column")
            if not sc or not tc or sc.strip().lower() == tc.strip().lower():
                continue
            con.execute(_t(f"""
                MERGE {STORE_SCHEMA}.dv_column_synonym AS t
                USING (SELECT :tc AS target_column, :al AS alias,
                              'global' AS scope, CAST(NULL AS nvarchar(128)) AS target_table) AS s
                  ON (t.target_column=s.target_column AND t.alias=s.alias
                      AND t.scope=s.scope AND t.target_table IS NULL)
                WHEN MATCHED THEN
                    UPDATE SET hit_count = t.hit_count + 1, confidence = :cf
                WHEN NOT MATCHED THEN
                    INSERT (target_column, alias, scope, confidence, row_created_by)
                    VALUES (:tc, :al, 'global', :cf, :by);
            """), {"tc": tc.strip().lower(), "al": sc.strip().lower(),
                   "cf": c.get("confidence"), "by": resolved_by})


# ── snapshots (versioned, fingerprint-keyed) ─────────────────────────────────
def build_table_spec(engine, target, columns, natural_key):
    """Convert a mapping (list of column dicts) into a dv_table_loader TableSpec
    so the existing loader can stage + BCP the file with full FK governance.

    Routing:
      • constant_value           -> spec.constants[target]
      • transform 'norm_uwi14'   -> spec.uwi_cols (loader normalizes to bare-14)
      • target is a SEED_ENTITY id (operator_ba_id, field_id) and a source is
        mapped to it -> spec.seed_from[target] = source (loader SHA-1 seeds it)
      • plain source -> source   -> spec.columns[source] = target
      • transform 'seq_within(...)' with no source -> spec.sequences (loader
        numbers rows 1..N within the natural-key group at load time).
    Returns (spec, skipped) where skipped is [(target_column, transform), ...]
    for any transform the loader still can't execute.
    """
    from dataview.mapping.dv_table_loader import TableSpec, discover_fks, _policy_for

    entity_ids = set()
    try:
        for fk in discover_fks(engine, target):
            strat, _ = _policy_for(fk.ref_table, None)
            if strat == "SEED_ENTITY":
                for lc, _rc in fk.cols:
                    entity_ids.add(lc)
    except Exception:
        pass

    cols, constants, uwi_cols, seed_from, sequences, skipped = {}, {}, [], {}, [], []
    for c in columns:
        tgt = c["target_column"]
        src = c.get("source_column")
        const = c.get("constant_value")
        tr = (c.get("transform") or "").strip()
        if const not in (None, ""):
            constants[tgt] = const
        elif not src:
            if tr.startswith("seq_within"):
                sequences.append(tgt)
            elif tr:
                skipped.append((tgt, tr))
        elif tgt in entity_ids:
            seed_from[tgt] = src
        else:
            cols[src] = tgt
            if tr == "norm_uwi14":
                uwi_cols.append(tgt)

    spec = TableSpec(target=target, natural_key=list(natural_key),
                     columns=cols, constants=constants,
                     uwi_cols=uwi_cols, seed_from=seed_from, sequences=sequences)
    return spec, skipped


def save_mapping(engine, table_type, domain, target_table, natural_key, columns,
                 source_columns, *, label=None, resolved_by="STEWARD"):
    """Snapshot one table's mapping as a NEW version, keyed by the source-layout
    fingerprint. Prior versions are retained; the new one becomes active. Also
    harvests confirmed column pairs into the synonym library."""
    ensure_store(engine)
    fp = fingerprint(source_columns)
    nk = ",".join(natural_key) if isinstance(natural_key, (list, tuple)) else (natural_key or "")
    with engine.begin() as con:
        ver = (con.execute(_t(f"""
            SELECT ISNULL(MAX(version), 0) FROM {STORE_SCHEMA}.dv_table_mapping
            WHERE source_fingerprint=:fp
        """), {"fp": fp}).scalar() or 0) + 1
        con.execute(_t(f"""UPDATE {STORE_SCHEMA}.dv_table_mapping SET is_active=0
                          WHERE source_fingerprint=:fp"""), {"fp": fp})
        mid = con.execute(_t(f"""
            INSERT INTO {STORE_SCHEMA}.dv_table_mapping
                (source_fingerprint, version, is_active, label, table_type, domain,
                 target_table, natural_key, source_columns, row_created_by)
            OUTPUT INSERTED.mapping_id
            VALUES (:fp, :ver, 1, :lbl, :tt, :d, :tg, :nk, :sc, :by)
        """), {"fp": fp, "ver": ver, "lbl": label, "tt": table_type, "d": domain,
               "tg": target_table, "nk": nk,
               "sc": json.dumps(list(source_columns)), "by": resolved_by}).scalar()
        for c in columns:
            con.execute(_t(f"""
                INSERT INTO {STORE_SCHEMA}.dv_table_mapping_col
                    (mapping_id, target_column, source_column, is_key, is_derived,
                     transform, constant_value, confidence, method)
                VALUES (:m, :tc, :sc, :k, :dr, :tr, :cv, :cf, :me)
            """), {"m": mid, "tc": c["target_column"], "sc": c.get("source_column"),
                   "k": int(c.get("is_key", 0)), "dr": int(c.get("is_derived", 0)),
                   "tr": c.get("transform"), "cv": c.get("constant_value"),
                   "cf": c.get("confidence"), "me": c.get("method")})
    harvest_synonyms(engine, columns, target_table, resolved_by=resolved_by)
    learn_signature(engine, source_columns, table_type, target_table,
                    domain=domain, label=label, resolved_by=resolved_by)
    return {"mapping_id": mid, "version": ver, "fingerprint": fp}


def load_snapshot_index(engine):
    """{fingerprint: meta} for all active snapshots in ONE query — so the scan
    detects snapshot hits without a per-file lookup. Returns {} if the store
    isn't there yet (nothing saved). Full columns load later, on demand."""
    try:
        with engine.connect() as con:
            rows = con.execute(_t(f"""
                SELECT source_fingerprint, version, label, table_type, domain, target_table
                FROM   {STORE_SCHEMA}.dv_table_mapping
                WHERE  is_active = 1
            """)).fetchall()
        return {r.source_fingerprint: {"version": r.version, "label": r.label,
                                       "table_type": r.table_type, "domain": r.domain,
                                       "target_table": r.target_table}
                for r in rows}
    except Exception:
        return {}


def find_snapshot(engine, source_cols):
    """Exact-fingerprint reload: if this source layout has been mapped before,
    return its ACTIVE snapshot {meta, columns}; else None. This is the
    'new data in the same format -> zero re-mapping' path."""
    fp = fingerprint(source_cols)
    with engine.connect() as con:
        m = con.execute(_t(f"""
            SELECT TOP 1 mapping_id, version, label, table_type, domain,
                   target_table, natural_key
            FROM   {STORE_SCHEMA}.dv_table_mapping
            WHERE  source_fingerprint=:fp AND is_active=1
            ORDER  BY version DESC
        """), {"fp": fp}).fetchone()
        if not m:
            return None
        cols = con.execute(_t(f"""
            SELECT target_column, source_column, is_key, is_derived, transform,
                   constant_value, confidence, method
            FROM {STORE_SCHEMA}.dv_table_mapping_col WHERE mapping_id=:m ORDER BY mapping_col_id
        """), {"m": m.mapping_id}).fetchall()
    return {"meta": {"mapping_id": m.mapping_id, "version": m.version, "label": m.label,
                     "table_type": m.table_type, "domain": m.domain,
                     "target_table": m.target_table, "fingerprint": fp,
                     "natural_key": (m.natural_key or "").split(",")},
            "columns": [dict(r._mapping) for r in cols]}


def closest_snapshots(engine, source_cols, *, table_type=None, top=3):
    """When there's no exact fingerprint match, suggest the nearest prior
    snapshots by source-column overlap (Jaccard), so a near-identical vendor
    file can start from an existing mapping instead of from scratch."""
    want = {str(c).strip().lower() for c in source_cols}
    q = f"""SELECT mapping_id, version, label, table_type, target_table, source_columns
           FROM {STORE_SCHEMA}.dv_table_mapping WHERE is_active=1"""
    params = {}
    if table_type:
        q += " AND table_type=:tt"
        params["tt"] = table_type
    out = []
    with engine.connect() as con:
        for r in con.execute(_t(q), params):
            try:
                cols = {c.strip().lower() for c in json.loads(r.source_columns or "[]")}
            except Exception:
                cols = set()
            if not cols:
                continue
            j = len(want & cols) / max(len(want | cols), 1)
            out.append({"mapping_id": r.mapping_id, "version": r.version,
                        "label": r.label, "table_type": r.table_type,
                        "target_table": r.target_table, "similarity": round(j, 2)})
    return sorted(out, key=lambda d: -d["similarity"])[:top]


# ── directory scan -> confirm list ───────────────────────────────────────────
def _count_lines(path):
    """Fast line count via binary newline counting — ~10-20x faster than
    iterating the csv reader, since it skips per-row parsing. Reads in 1 MB
    chunks. Approximate only if fields contain embedded newlines (rare in well
    data), which is fine for a confirm-grid row estimate."""
    total = 0
    with open(path, "rb") as fb:
        while True:
            chunk = fb.read(1 << 20)
            if not chunk:
                break
            total += chunk.count(b"\n")
    return total


def _peek(path):
    """Return (header_columns, data_row_count) for a delimited file, or (None,0)
    if unreadable. Sniffs the delimiter from a sample; counts rows cheaply."""
    import csv as _csv
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace",
                  newline="") as fh:
            sample = fh.read(65536)
        if not sample.strip():
            return [], 0
        if path.lower().endswith(".tsv"):
            delim = "\t"
        else:
            try:
                delim = _csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except Exception:
                delim = ","
        first_line = sample.split("\n", 1)[0]
        header = next(_csv.reader([first_line], delimiter=delim), [])
        header = [h.strip() for h in header if h.strip() != ""]
        nrows = max(_count_lines(path) - 1, 0)          # minus the header line
        return header, nrows
    except Exception:
        return None, 0


def _walk(root, exts, recursive):
    import os
    exts = tuple(e.lower() for e in exts)
    if recursive:
        for dp, _dn, fn in os.walk(root):
            for f in fn:
                if f.lower().endswith(exts):
                    yield os.path.join(dp, f)
    else:
        for f in os.listdir(root):
            p = os.path.join(root, f)
            if os.path.isfile(p) and f.lower().endswith(exts):
                yield p


def scan_directory(engine, root, *, exts=(".csv", ".tsv"), recursive=True,
                   schema=None, rarity=None, timings=None):
    """Walk `root`, classify each delimited file, check for a snapshot hit, count
    rows, and return the confirm list ordered parents-first by the FK graph.

    `schema`/`rarity` may be passed in (cached by the page) to avoid re-querying
    on every scan. `timings` (optional dict) is filled with per-phase seconds.
    Each item:
      {file, name, columns, rows, domain, table_type, target_table, score,
       snapshot (bool), snapshot_label, candidates, status}
    status: 'snapshot' (exact reload) | 'detected' | 'ambiguous' | 'unknown'
    """
    import os
    T = timings if timings is not None else {}

    def _phase(name, fn):
        t0 = time.time()
        r = fn()
        T[name] = time.time() - t0
        return r

    items = []
    learned = _phase("learned signatures", lambda: load_learned_signatures(engine))
    if schema is None:
        schema = _phase("schema introspection", lambda: load_schema(engine))
        rarity = _phase("column rarity",
                        lambda: column_rarity(schema) if schema else None)
    elif rarity is None:
        rarity = column_rarity(schema) if schema else None
    snap_index = _phase("snapshot index", lambda: load_snapshot_index(engine))
    schema_canon = _phase("canonicalize schema", lambda: build_schema_canon(schema))

    t_files = time.time()
    n_files = 0
    for path in _walk(root, exts, recursive):
        n_files += 1
        header, nrows = _peek(path)
        name = os.path.basename(path)
        if not header:
            items.append({"file": path, "name": name, "columns": [], "rows": 0,
                          "domain": None, "table_type": None, "target_table": None,
                          "score": 0.0, "snapshot": False, "snapshot_label": None,
                          "candidates": [], "status": "unknown", "filename_clue": None})
            continue
        cands = classify(header, filename=name, learned=learned,
                         schema=schema, rarity=rarity, schema_canon=schema_canon)
        clue = filename_clue(name)
        m = snap_index.get(fingerprint(header))         # in-memory, no per-file query
        if m:
            items.append({"file": path, "name": name, "columns": header, "rows": nrows,
                          "domain": m.get("domain"), "table_type": m["table_type"],
                          "target_table": m["target_table"], "score": 1.0,
                          "snapshot": True, "snapshot_label": m.get("label"),
                          "candidates": cands, "status": "snapshot", "filename_clue": clue})
        elif cands:
            top = cands[0]
            ambiguous = (len(cands) > 1
                         and (cands[0]["score"] - cands[1]["score"]) < 0.15
                         and not cands[0].get("filename_hit"))
            learned_hit = top.get("source") == "learned"
            items.append({"file": path, "name": name, "columns": header, "rows": nrows,
                          "domain": top["domain"], "table_type": top["table_type"],
                          "target_table": top["target_table"], "score": top["score"],
                          "snapshot": False, "snapshot_label": None,
                          "candidates": cands, "filename_clue": clue,
                          "status": "learned" if learned_hit else
                                    ("ambiguous" if ambiguous else "detected")})
        else:
            items.append({"file": path, "name": name, "columns": header, "rows": nrows,
                          "domain": None, "table_type": None, "target_table": None,
                          "score": 0.0, "snapshot": False, "snapshot_label": None,
                          "candidates": [], "status": "unknown", "filename_clue": clue})
    T[f"scan + classify ({n_files} files)"] = time.time() - t_files

    t_ord = time.time()
    ordered = order_by_dependency(engine, items)
    T["dependency ordering"] = time.time() - t_ord
    T["total"] = sum(v for k, v in T.items() if k != "total")
    return ordered


def order_by_dependency(engine, items):
    """Topologically sort confirm-list items so a target loads after any target
    it references by FK (well -> survey hdr -> survey stations). Items without a
    target, or unresolved cycles, fall to the end in stable order."""
    try:
        from dataview.mapping.dv_table_loader import discover_fks
    except Exception:
        return items
    targets = {it["target_table"] for it in items if it.get("target_table")}
    deps = {}                                   # target -> set(targets it references)
    for tg in targets:
        d = set()
        try:
            for fk in discover_fks(engine, tg):
                if fk.ref_table in targets and fk.ref_table != tg:
                    d.add(fk.ref_table)
        except Exception:
            pass
        deps[tg] = d
    # Kahn topological order over targets
    ordered, ready = [], sorted(t for t, d in deps.items() if not d)
    remaining = {t: set(d) for t, d in deps.items()}
    while ready:
        t = ready.pop(0)
        ordered.append(t)
        for u in list(remaining):
            remaining[u].discard(t)
            if u != t and not remaining[u] and u not in ordered and u not in ready:
                ready.append(u)
        ready.sort()
        remaining.pop(t, None)
    ordered += [t for t in deps if t not in ordered]      # any leftover (cycles)
    rank = {t: i for i, t in enumerate(ordered)}
    return sorted(items, key=lambda it: (rank.get(it.get("target_table"), 1_000_000),
                                         it["name"]))
