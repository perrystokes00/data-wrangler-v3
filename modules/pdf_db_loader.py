"""
modules/pdf_db_loader.py
==========================
PPDM 3.9 loaders for all PDF-extracted document types.

Each loader follows the same contract:
    load_<type>(engine, dialect, well_info, rows, source, row_quality) -> dict
    returns {"ok": bool, "loaded": int, "errors": [...], "ids": {...}}

Load chains:
  Formation Tops  → STRAT_NAME_SET → STRAT_UNIT → STRAT_WELL_SECTION
  DST / Well Test → WELL_TEST → WELL_TEST_PERIOD → WELL_TEST_FLOW / WELL_TEST_PRESSURE
  RFT / MDT       → WELL_TEST (test_type='RFT') → WELL_TEST_PRESSURE
  Core Data       → WELL_CORE → WELL_CORE_ANALYSIS → WELL_CORE_SAMPLE_ANAL
  Scout Ticket    → WELL (UPDATE surface location + IP remark)
  EOWR            → WELL_CORE (strat summary as remark) [simplified]
  Casing/Cement   → WELL_COMPLETION → WELL_COMPONENT

All require UWI to exist in dataview.dv_well.
All use ppdm_guid (newid() / sys_guid() / uuid_string()).
"""
from __future__ import annotations
import uuid
from sqlalchemy import text


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now(dialect: str) -> str:
    return {"oracle": "SYSTIMESTAMP",
            "snowflake": "CURRENT_TIMESTAMP()"}.get(dialect, "GETUTCDATE()")

def _guid(dialect: str) -> str:
    return {"oracle": "SYS_GUID()",
            "snowflake": "UUID_STRING()"}.get(dialect, "NEWID()")

def _uid() -> str:
    return uuid.uuid4().hex[:40].upper()

def _trunc(v, n=40):
    return str(v)[:n] if v is not None else None

def _safe_float(v):
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None

def _normalize_uwi(uwi: str) -> str:
    """Strip dashes, spaces and slashes for fuzzy matching."""
    import re
    return re.sub(r"[\-\s/]", "", str(uwi or "")).upper()

def _resolve_uwi(con, uwi: str, uwi_override: str = None) -> str | None:
    """
    Resolve a UWI to the canonical value stored in dataview.dv_well.

    Resolution order:
      1. If uwi_override is provided, use it as-is (user explicitly chose it).
      2. Exact match on uwi.
      3. Normalized match — strip dashes/spaces/slashes from both sides.

    Returns the matched UWI string, or None if not found.
    """
    check = uwi_override or uwi
    if not check:
        return None

    # 1. Exact match
    row = con.execute(text(
        "SELECT UWI FROM dataview.dv_well WHERE UWI = :u"
    ), {"u": check}).fetchone()
    if row:
        return row[0]

    # 2. Normalized match — digits and letters only
    norm = _normalize_uwi(check)
    if not norm:
        return None

    row = con.execute(text("""
        SELECT UWI FROM dataview.dv_well
        WHERE REPLACE(REPLACE(REPLACE(UWI, '-', ''), ' ', ''), '/', '') = :n
    """), {"n": norm}).fetchone()
    if row:
        return row[0]

    return None


def _bootstrap_well(con, dialect: str, well_info: dict,
                    source: str = "PDF_HEADER") -> str | None:
    """
    Create a dv_well row from PDF header fields when lat/lon is available
    and no existing well match was found.

    Returns the new UWI on success, None if lat/lon is missing or insert fails.
    """
    uwi  = _trunc(well_info.get("uwi"), 40)
    lat  = _safe_float(well_info.get("latitude"))
    lon  = _safe_float(well_info.get("longitude"))

    # Require both UWI and coordinates to auto-create
    if not uwi or lat is None or lon is None:
        return None

    now = _now(dialect)
    wn  = _trunc(well_info.get("well_name") or uwi, 255)
    try:
        con.execute(text(f"""
            INSERT INTO dataview.dv_well (
                UWI, WELL_NAME,
                SURFACE_LATITUDE, SURFACE_LONGITUDE,
                FINAL_TD,
                ACTIVE_IND, SOURCE,
                PPDM_GUID,
                ROW_CREATED_BY, ROW_CREATED_DATE,
                ROW_CHANGED_BY, ROW_CHANGED_DATE,
                ROW_QUALITY
            ) VALUES (
                :uwi, :wn,
                :lat, :lon,
                :td,
                'Y', :src,
                {_guid(dialect)},
                :by, {now}, :by, {now},
                'FINAL'
            )
        """), {
            "uwi": uwi,
            "wn":  wn,
            "lat": lat,
            "lon": lon,
            "td":  _safe_float(well_info.get("total_depth")),
            "src": source,
            "by":  "DataWrangler",
        })
        return uwi
    except Exception:
        return None


def _well_exists(con, uwi: str) -> bool:
    """Legacy helper — use _resolve_uwi for new code."""
    return _resolve_uwi(con, uwi) is not None

def _result(loaded=0, errors=None, **ids):
    return {"ok": not errors, "loaded": loaded,
            "errors": errors or [], "ids": ids}


# ══════════════════════════════════════════════════════════════════════════════
# Formation Tops
# STRAT_NAME_SET → STRAT_UNIT (one per formation) → STRAT_WELL_SECTION
# ══════════════════════════════════════════════════════════════════════════════

def load_formation_tops(engine, dialect: str, well_info: dict,
                        rows: list[dict], source: str = "DATA_LOADER",
                        row_quality: str = "FINAL") -> dict:
    """
    Load formation tops extracted from a PDF.

    rows: [{"FORMATION_NAME": str, "DEPTH_TOP_MD": float}, ...]
    """
    now = _now(dialect)
    uwi = _trunc(well_info.get("uwi"), 40)
    if not uwi:
        return _result(errors=["No UWI provided"])
    if not rows:
        return _result(errors=["No formation tops to load"])

    name_set_id = _uid()
    well_name   = _trunc(well_info.get("well_name") or uwi, 255)
    errors      = []
    loaded      = 0

    bootstrapped = False
    try:
        with engine.begin() as con:
            # Resolve UWI — exact then normalized (strips dashes/spaces)
            uwi_override = _trunc(well_info.get("uwi_override"), 40)
            resolved = _resolve_uwi(con, uwi, uwi_override)
            if not resolved:
                # Attempt to bootstrap from header if lat/lon present
                resolved = _bootstrap_well(con, dialect, well_info, source=source)
                if resolved:
                    bootstrapped = True
            if not resolved:
                return _result(errors=[
                    f"UWI '{uwi}' not found in dataview.dv_well "
                    f"(tried exact + normalized match). "
                    f"Provide lat/lon in header to auto-create well."
                ])
            uwi = resolved  # use canonical matched UWI for all inserts

            # ── 1. STRAT_NAME_SET ─────────────────────────────────────────────
            con.execute(text(f"""
                INSERT INTO dataview.dv_well_formation_top (
                    STRAT_NAME_SET_ID, STRAT_NAME_SET_NAME,
                    STRAT_NAME_SET_TYPE, SOURCE,
                    ACTIVE_IND, PREFERRED_IND,
                    PPDM_GUID,
                    ROW_CREATED_BY, ROW_CREATED_DATE,
                    ROW_CHANGED_BY, ROW_CHANGED_DATE,
                    ROW_QUALITY
                ) VALUES (
                    :sid, :sname,
                    'WELL', :src,
                    'Y', 'Y',
                    {_guid(dialect)},
                    :by, {now}, :by, {now}, :rq
                )
            """), {
                "sid":   name_set_id,
                "sname": _trunc(f"{well_name} Formation Tops", 255),
                "src":   source,
                "by":    "DataWrangler",
                "rq":    row_quality,
            })

            # ── 2. STRAT_UNIT + STRAT_WELL_SECTION per formation ──────────────
            for obs_no, row in enumerate(rows, start=1):
                form_name = _trunc(row.get("FORMATION_NAME", f"FORMATION_{obs_no}"), 40)
                depth_md  = row.get("DEPTH_TOP_MD")
                unit_id   = _uid()
                interp_id = _uid()

                try:
                    # STRAT_UNIT
                    con.execute(text(f"""
                        INSERT INTO dataview.dv_well_formation_top (
                            STRAT_NAME_SET_ID, STRAT_UNIT_ID,
                            LONG_NAME, SHORT_NAME,
                            STRAT_UNIT_TYPE, SOURCE,
                            ACTIVE_IND, PREFERRED_IND,
                            PPDM_GUID,
                            ROW_CREATED_BY, ROW_CREATED_DATE,
                            ROW_CHANGED_BY, ROW_CHANGED_DATE,
                            ROW_QUALITY
                        ) VALUES (
                            :nsid, :uid,
                            :lname, :sname,
                            'FORMATION', :src,
                            'Y', 'Y',
                            {_guid(dialect)},
                            :by, {now}, :by, {now}, :rq
                        )
                    """), {
                        "nsid":  name_set_id,
                        "uid":   unit_id,
                        "lname": _trunc(form_name, 255),
                        "sname": _trunc(form_name, 30),
                        "src":   source,
                        "by":    "DataWrangler",
                        "rq":    row_quality,
                    })

                    # STRAT_WELL_SECTION
                    con.execute(text(f"""
                        INSERT INTO dataview.dv_well_formation_top (
                            UWI, STRAT_NAME_SET_ID, STRAT_UNIT_ID, INTERP_ID,
                            PICK_DEPTH, PICK_DEPTH_OUOM,
                            SOURCE, ACTIVE_IND, PREFERRED_PICK_IND,
                            ORDINAL_SEQ_NO,
                            PPDM_GUID,
                            ROW_CREATED_BY, ROW_CREATED_DATE,
                            ROW_CHANGED_BY, ROW_CHANGED_DATE,
                            ROW_QUALITY
                        ) VALUES (
                            :uwi, :nsid, :uid, :iid,
                            :depth, 'ft',
                            :src, 'Y', 'Y',
                            :obs,
                            {_guid(dialect)},
                            :by, {now}, :by, {now}, :rq
                        )
                    """), {
                        "uwi":   uwi,
                        "nsid":  name_set_id,
                        "uid":   unit_id,
                        "iid":   interp_id,
                        "depth": depth_md,
                        "src":   source,
                        "obs":   obs_no,
                        "by":    "DataWrangler",
                        "rq":    row_quality,
                    })
                    loaded += 1

                except Exception as e:
                    errors.append(f"{form_name}: {e}")

    except Exception as e:
        return _result(errors=[str(e)])

    return _result(loaded=loaded, errors=errors,
                   strat_name_set_id=name_set_id)


# ══════════════════════════════════════════════════════════════════════════════
# DST / Well Test
# WELL_TEST → WELL_TEST_PERIOD (one per flow/shut-in period)
# ══════════════════════════════════════════════════════════════════════════════

def load_well_test(engine, dialect: str, well_info: dict,
                   rows: list[dict], source: str = "DATA_LOADER",
                   row_quality: str = "FINAL",
                   test_type: str = "DST") -> dict:
    """
    Load DST or well test data.

    rows: [{"PERIOD", "TYPE", "DURATION", "OIL_BOPD", "GAS_MCFD",
             "WATER_BWPD", "FWHP", "FBHP"}, ...]
    well_info: may contain STATIC_PRESSURE, PERMEABILITY, SKIN, PI etc.
    """
    now = _now(dialect)
    uwi = _trunc(well_info.get("uwi"), 40)
    if not uwi:
        return _result(errors=["No UWI provided"])

    run_num  = "1"
    test_num = "1"
    errors   = []
    loaded   = 0

    bootstrapped = False
    try:
        with engine.begin() as con:
            # Resolve UWI — exact then normalized (strips dashes/spaces)
            uwi_override = _trunc(well_info.get("uwi_override"), 40)
            resolved = _resolve_uwi(con, uwi, uwi_override)
            if not resolved:
                # Attempt to bootstrap from header if lat/lon present
                resolved = _bootstrap_well(con, dialect, well_info, source=source)
                if resolved:
                    bootstrapped = True
            if not resolved:
                return _result(errors=[
                    f"UWI '{uwi}' not found in dataview.dv_well "
                    f"(tried exact + normalized match). "
                    f"Provide lat/lon in header to auto-create well."
                ])
            uwi = resolved  # use canonical matched UWI for all inserts

            # ── WELL_TEST header ──────────────────────────────────────────────
            analysis = well_info  # contains STATIC_PRESSURE, PERMEABILITY etc.
            con.execute(text(f"""
                INSERT INTO dataview.dv_well_TEST (
                    UWI, SOURCE, TEST_TYPE, RUN_NUM, TEST_NUM,
                    TOP_DEPTH, BASE_DEPTH,
                    STATIC_PRESSURE,
                    ACTIVE_IND,
                    PPDM_GUID,
                    ROW_CREATED_BY, ROW_CREATED_DATE,
                    ROW_CHANGED_BY, ROW_CHANGED_DATE,
                    ROW_QUALITY
                ) VALUES (
                    :uwi, :src, :ttype, :rnum, :tnum,
                    :top, :base,
                    :sp,
                    'Y',
                    {_guid(dialect)},
                    :by, {now}, :by, {now}, :rq
                )
            """), {
                "uwi":   uwi,
                "src":   source,
                "ttype": _trunc(test_type, 40),
                "rnum":  run_num,
                "tnum":  test_num,
                "top":   _safe_float(well_info.get("INTERVAL_TOP")),
                "base":  _safe_float(well_info.get("INTERVAL_BOT")),
                "sp":    _safe_float(analysis.get("STATIC_PRESSURE")),
                "by":    "DataWrangler",
                "rq":    row_quality,
            })

            # ── WELL_TEST_PERIOD per flow/shut-in period ──────────────────────
            for obs_no, row in enumerate(rows, start=1):
                period_type = _trunc(
                    "FLOW" if str(row.get("TYPE","")).upper() in ("FLOW","FLOW PERIOD","F")
                    else "SHUTIN", 40
                )
                try:
                    con.execute(text(f"""
                        INSERT INTO dataview.dv_well_TEST_PERIOD (
                            UWI, SOURCE, TEST_TYPE, RUN_NUM, TEST_NUM,
                            PERIOD_TYPE, PERIOD_OBS_NO,
                            PERIOD_DURATION,
                            TUBING_PRESSURE, CASING_PRESSURE,
                            ACTIVE_IND,
                            PPDM_GUID,
                            ROW_CREATED_BY, ROW_CREATED_DATE,
                            ROW_CHANGED_BY, ROW_CHANGED_DATE,
                            ROW_QUALITY
                        ) VALUES (
                            :uwi, :src, :ttype, :rnum, :tnum,
                            :ptype, :obs,
                            :dur,
                            :fwhp, :fbhp,
                            'Y',
                            {_guid(dialect)},
                            :by, {now}, :by, {now}, :rq
                        )
                    """), {
                        "uwi":   uwi,
                        "src":   source,
                        "ttype": _trunc(test_type, 40),
                        "rnum":  run_num,
                        "tnum":  test_num,
                        "ptype": period_type,
                        "obs":   obs_no,
                        "dur":   _safe_float(row.get("DURATION")),
                        "fwhp":  _safe_float(row.get("FWHP")),
                        "fbhp":  _safe_float(row.get("FBHP")),
                        "by":    "DataWrangler",
                        "rq":    row_quality,
                    })
                    loaded += 1
                except Exception as e:
                    errors.append(f"Period {obs_no}: {e}")

    except Exception as e:
        return _result(errors=[str(e)])

    return _result(loaded=loaded, errors=errors)


# ══════════════════════════════════════════════════════════════════════════════
# RFT / MDT  (same tables as well test, test_type = 'RFT')
# WELL_TEST → WELL_TEST_PRESSURE (one row per measurement depth)
# ══════════════════════════════════════════════════════════════════════════════

def load_rft(engine, dialect: str, well_info: dict,
             rows: list[dict], source: str = "DATA_LOADER",
             row_quality: str = "FINAL") -> dict:
    """
    rows: [{"DEPTH_MD", "PRESSURE", "FORMATION", "FLUID_TYPE",
             "MOBILITY", "GRADIENT"}, ...]
    """
    now = _now(dialect)
    uwi = _trunc(well_info.get("uwi"), 40)
    if not uwi:
        return _result(errors=["No UWI provided"])

    run_num  = "1"
    test_num = "1"
    period_type = "FLOW"
    errors   = []
    loaded   = 0

    bootstrapped = False
    try:
        with engine.begin() as con:
            # Resolve UWI — exact then normalized (strips dashes/spaces)
            uwi_override = _trunc(well_info.get("uwi_override"), 40)
            resolved = _resolve_uwi(con, uwi, uwi_override)
            if not resolved:
                # Attempt to bootstrap from header if lat/lon present
                resolved = _bootstrap_well(con, dialect, well_info, source=source)
                if resolved:
                    bootstrapped = True
            if not resolved:
                return _result(errors=[
                    f"UWI '{uwi}' not found in dataview.dv_well "
                    f"(tried exact + normalized match). "
                    f"Provide lat/lon in header to auto-create well."
                ])
            uwi = resolved  # use canonical matched UWI for all inserts

            # WELL_TEST header
            con.execute(text(f"""
                INSERT INTO dataview.dv_well_TEST (
                    UWI, SOURCE, TEST_TYPE, RUN_NUM, TEST_NUM,
                    ACTIVE_IND, PPDM_GUID,
                    ROW_CREATED_BY, ROW_CREATED_DATE,
                    ROW_CHANGED_BY, ROW_CHANGED_DATE, ROW_QUALITY
                ) VALUES (
                    :uwi, :src, 'RFT', :rnum, :tnum,
                    'Y', {_guid(dialect)},
                    :by, {now}, :by, {now}, :rq
                )
            """), {"uwi": uwi, "src": source, "rnum": run_num,
                   "tnum": test_num, "by": "DataWrangler", "rq": row_quality})

            # One WELL_TEST_PERIOD for the whole run
            con.execute(text(f"""
                INSERT INTO dataview.dv_well_TEST_PERIOD (
                    UWI, SOURCE, TEST_TYPE, RUN_NUM, TEST_NUM,
                    PERIOD_TYPE, PERIOD_OBS_NO,
                    ACTIVE_IND, PPDM_GUID,
                    ROW_CREATED_BY, ROW_CREATED_DATE,
                    ROW_CHANGED_BY, ROW_CHANGED_DATE, ROW_QUALITY
                ) VALUES (
                    :uwi, :src, 'RFT', :rnum, :tnum,
                    :ptype, 1,
                    'Y', {_guid(dialect)},
                    :by, {now}, :by, {now}, :rq
                )
            """), {"uwi": uwi, "src": source, "rnum": run_num,
                   "tnum": test_num, "ptype": period_type,
                   "by": "DataWrangler", "rq": row_quality})

            # WELL_TEST_PRESSURE per measurement point
            for obs_no, row in enumerate(rows, start=1):
                try:
                    con.execute(text(f"""
                        INSERT INTO dataview.dv_well_TEST_PRESSURE (
                            UWI, SOURCE, TEST_TYPE, RUN_NUM, TEST_NUM,
                            PERIOD_TYPE, PERIOD_OBS_NO,
                            START_PRESSURE, END_PRESSURE,
                            SUMMARY_IND,
                            PPDM_GUID,
                            ROW_CREATED_BY, ROW_CREATED_DATE,
                            ROW_CHANGED_BY, ROW_CHANGED_DATE, ROW_QUALITY
                        ) VALUES (
                            :uwi, :src, 'RFT', :rnum, :tnum,
                            :ptype, 1,
                            :press, :press,
                            'Y',
                            {_guid(dialect)},
                            :by, {now}, :by, {now}, :rq
                        )
                    """), {
                        "uwi":   uwi, "src": source,
                        "rnum":  run_num, "tnum": test_num,
                        "ptype": period_type,
                        "press": _safe_float(row.get("PRESSURE")),
                        "by":    "DataWrangler", "rq": row_quality,
                    })
                    loaded += 1
                except Exception as e:
                    errors.append(f"RFT point {obs_no}: {e}")

    except Exception as e:
        return _result(errors=[str(e)])

    return _result(loaded=loaded, errors=errors)


# ══════════════════════════════════════════════════════════════════════════════
# Core Data
# WELL_CORE → WELL_CORE_ANALYSIS → WELL_CORE_SAMPLE_ANAL (one per depth)
# ══════════════════════════════════════════════════════════════════════════════

def load_core(engine, dialect: str, well_info: dict,
              rows: list[dict], source: str = "DATA_LOADER",
              row_quality: str = "FINAL") -> dict:
    """
    rows: [{"DEPTH", "POROSITY", "PERMEABILITY", "SW"}, ...]
    """
    now = _now(dialect)
    uwi = _trunc(well_info.get("uwi"), 40)
    if not uwi:
        return _result(errors=["No UWI provided"])
    if not rows:
        return _result(errors=["No core samples to load"])

    core_id    = _uid()
    anal_obs   = 1
    depths     = [r.get("DEPTH") for r in rows if r.get("DEPTH") is not None]
    top_depth  = min(depths) if depths else None
    base_depth = max(depths) if depths else None
    errors     = []
    loaded     = 0

    bootstrapped = False
    try:
        with engine.begin() as con:
            # Resolve UWI — exact then normalized (strips dashes/spaces)
            uwi_override = _trunc(well_info.get("uwi_override"), 40)
            resolved = _resolve_uwi(con, uwi, uwi_override)
            if not resolved:
                # Attempt to bootstrap from header if lat/lon present
                resolved = _bootstrap_well(con, dialect, well_info, source=source)
                if resolved:
                    bootstrapped = True
            if not resolved:
                return _result(errors=[
                    f"UWI '{uwi}' not found in dataview.dv_well "
                    f"(tried exact + normalized match). "
                    f"Provide lat/lon in header to auto-create well."
                ])
            uwi = resolved  # use canonical matched UWI for all inserts

            # ── WELL_CORE header ──────────────────────────────────────────────
            con.execute(text(f"""
                INSERT INTO dataview.dv_well_CORE (
                    UWI, SOURCE, CORE_ID,
                    TOP_DEPTH, TOP_DEPTH_OUOM,
                    BASE_DEPTH, BASE_DEPTH_OUOM,
                    ACTIVE_IND, SIDEWALL_IND,
                    PPDM_GUID,
                    ROW_CREATED_BY, ROW_CREATED_DATE,
                    ROW_CHANGED_BY, ROW_CHANGED_DATE, ROW_QUALITY
                ) VALUES (
                    :uwi, :src, :cid,
                    :top, 'ft', :base, 'ft',
                    'Y', 'N',
                    {_guid(dialect)},
                    :by, {now}, :by, {now}, :rq
                )
            """), {"uwi": uwi, "src": source, "cid": core_id,
                   "top": top_depth, "base": base_depth,
                   "by": "DataWrangler", "rq": row_quality})

            # ── WELL_CORE_ANALYSIS ────────────────────────────────────────────
            con.execute(text(f"""
                INSERT INTO dataview.dv_well_CORE_ANALYSIS (
                    UWI, SOURCE, CORE_ID, ANALYSIS_OBS_NO,
                    ACTIVE_IND, PPDM_GUID,
                    ROW_CREATED_BY, ROW_CREATED_DATE,
                    ROW_CHANGED_BY, ROW_CHANGED_DATE, ROW_QUALITY
                ) VALUES (
                    :uwi, :src, :cid, :obs,
                    'Y', {_guid(dialect)},
                    :by, {now}, :by, {now}, :rq
                )
            """), {"uwi": uwi, "src": source, "cid": core_id,
                   "obs": anal_obs, "by": "DataWrangler", "rq": row_quality})

            # ── WELL_CORE_SAMPLE_ANAL per depth ───────────────────────────────
            for i, row in enumerate(rows, start=1):
                try:
                    con.execute(text(f"""
                        INSERT INTO dataview.dv_well_CORE_SAMPLE_ANAL (
                            UWI, SOURCE, CORE_ID,
                            ANALYSIS_OBS_NO, SAMPLE_NUM, SAMPLE_ANALYSIS_OBS_NO,
                            TOP_DEPTH, TOP_DEPTH_OUOM,
                            INTERVAL_DEPTH, INTERVAL_DEPTH_OUOM,
                            POROSITY, EFFECTIVE_POROSITY,
                            KMAX, KMAX_OUOM,
                            WATER_SAT,
                            PPDM_GUID,
                            ROW_CREATED_BY, ROW_CREATED_DATE,
                            ROW_CHANGED_BY, ROW_CHANGED_DATE, ROW_QUALITY
                        ) VALUES (
                            :uwi, :src, :cid,
                            :aobs, :snum, :saobs,
                            :depth, 'ft', :depth, 'ft',
                            :por, :por,
                            :perm, 'mD',
                            :sw,
                            {_guid(dialect)},
                            :by, {now}, :by, {now}, :rq
                        )
                    """), {
                        "uwi":   uwi, "src": source, "cid": core_id,
                        "aobs":  anal_obs,
                        "snum":  str(i),
                        "saobs": i,
                        "depth": _safe_float(row.get("DEPTH")),
                        "por":   _safe_float(row.get("POROSITY")),
                        "perm":  _safe_float(row.get("PERMEABILITY")),
                        "sw":    _safe_float(row.get("SW")),
                        "by":    "DataWrangler", "rq": row_quality,
                    })
                    loaded += 1
                except Exception as e:
                    errors.append(f"Sample {i}: {e}")

    except Exception as e:
        return _result(errors=[str(e)])

    return _result(loaded=loaded, errors=errors, core_id=core_id)


# ══════════════════════════════════════════════════════════════════════════════
# Casing & Cementing → WELL_COMPLETION
# ══════════════════════════════════════════════════════════════════════════════

def load_casing(engine, dialect: str, well_info: dict,
                rows: list[dict], source: str = "DATA_LOADER",
                row_quality: str = "FINAL") -> dict:
    """
    rows: [{"STRING", "OD (IN)", "WEIGHT (PPF)", "GRADE",
             "SHOE DEPTH (FT MD)", "SHOE DEPTH (FT TVD)"}, ...]
    """
    now    = _now(dialect)
    uwi    = _trunc(well_info.get("uwi"), 40)
    errors = []
    loaded = 0

    if not uwi:
        return _result(errors=["No UWI provided"])

    bootstrapped = False
    try:
        with engine.begin() as con:
            # Resolve UWI — exact then normalized (strips dashes/spaces)
            uwi_override = _trunc(well_info.get("uwi_override"), 40)
            resolved = _resolve_uwi(con, uwi, uwi_override)
            if not resolved:
                # Attempt to bootstrap from header if lat/lon present
                resolved = _bootstrap_well(con, dialect, well_info, source=source)
                if resolved:
                    bootstrapped = True
            if not resolved:
                return _result(errors=[
                    f"UWI '{uwi}' not found in dataview.dv_well "
                    f"(tried exact + normalized match). "
                    f"Provide lat/lon in header to auto-create well."
                ])
            uwi = resolved  # use canonical matched UWI for all inserts

            for obs_no, row in enumerate(rows, start=1):
                # Find depth column — key names vary
                top_depth  = None
                base_depth = _safe_float(
                    row.get("SHOE DEPTH (FT MD)") or
                    row.get("SHOE DEPTH") or
                    row.get("BASE_DEPTH")
                )
                remark = (
                    f"{row.get('STRING','')} "
                    f"{row.get('OD (IN)','')}" "\" "
                    f"{row.get('WEIGHT (PPF)','')} ppf "
                    f"{row.get('GRADE','')}"
                ).strip()

                try:
                    con.execute(text(f"""
                        INSERT INTO dataview.dv_well_COMPLETION (
                            UWI, SOURCE, COMPLETION_OBS_NO,
                            TOP_DEPTH, TOP_DEPTH_OUOM,
                            BASE_DEPTH, BASE_DEPTH_OUOM,
                            REMARK,
                            ACTIVE_IND,
                            PPDM_GUID,
                            ROW_CREATED_BY, ROW_CREATED_DATE,
                            ROW_CHANGED_BY, ROW_CHANGED_DATE, ROW_QUALITY
                        ) VALUES (
                            :uwi, :src, :obs,
                            :top, 'ft', :base, 'ft',
                            :rmk,
                            'Y',
                            {_guid(dialect)},
                            :by, {now}, :by, {now}, :rq
                        )
                    """), {
                        "uwi":  uwi, "src": source, "obs": obs_no,
                        "top":  top_depth, "base": base_depth,
                        "rmk":  _trunc(remark, 2000),
                        "by":   "DataWrangler", "rq": row_quality,
                    })
                    loaded += 1
                except Exception as e:
                    errors.append(f"String {obs_no}: {e}")

    except Exception as e:
        return _result(errors=[str(e)])

    return _result(loaded=loaded, errors=errors)


# ══════════════════════════════════════════════════════════════════════════════
# Scout Ticket → UPDATE WELL with IP data stored as REMARK
# ══════════════════════════════════════════════════════════════════════════════

def load_scout(engine, dialect: str, well_info: dict,
               rows: list[dict], source: str = "DATA_LOADER",
               row_quality: str = "FINAL") -> dict:
    """
    Updates dataview.dv_well REMARK with IP summary from scout ticket.
    rows: IP table rows
    """
    now = _now(dialect)
    uwi = _trunc(well_info.get("uwi"), 40)
    if not uwi:
        return _result(errors=["No UWI provided"])

    # Build IP summary remark
    ip_lines = []
    for r in rows[:5]:  # first 5 test periods
        parts = []
        if r.get("OIL_BOPD"):  parts.append(f"Oil: {r['OIL_BOPD']} bbl/d")
        if r.get("GAS_MCFD"):  parts.append(f"Gas: {r['GAS_MCFD']} Mcf/d")
        if r.get("WATER_BWPD"):parts.append(f"Water: {r['WATER_BWPD']} bbl/d")
        if parts:
            ip_lines.append(f"[{r.get('DATE','')}] " + " | ".join(parts))
    remark = "Scout IP: " + "; ".join(ip_lines) if ip_lines else "Scout ticket imported"

    bootstrapped = False
    try:
        with engine.begin() as con:
            # Resolve UWI — exact then normalized (strips dashes/spaces)
            uwi_override = _trunc(well_info.get("uwi_override"), 40)
            resolved = _resolve_uwi(con, uwi, uwi_override)
            if not resolved:
                # Attempt to bootstrap from header if lat/lon present
                resolved = _bootstrap_well(con, dialect, well_info, source=source)
                if resolved:
                    bootstrapped = True
            if not resolved:
                return _result(errors=[
                    f"UWI '{uwi}' not found in dataview.dv_well "
                    f"(tried exact + normalized match). "
                    f"Provide lat/lon in header to auto-create well."
                ])
            uwi = resolved  # use canonical matched UWI for all inserts

            con.execute(text(f"""
                UPDATE dataview.dv_well SET
                    REMARK           = :rmk,
                    ROW_CHANGED_BY   = :by,
                    ROW_CHANGED_DATE = {now}
                WHERE UWI = :uwi
            """), {"rmk": _trunc(remark, 2000), "by": "DataWrangler", "uwi": uwi})

    except Exception as e:
        return _result(errors=[str(e)])

    return _result(loaded=1)


# ── (utility functions in helpers section above) ──────────────────────────────
