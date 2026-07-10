# Generate the widened V_WELL_FEDERATION. One row of 33 expressions per source;
# asserted to keep every UNION branch aligned.
COLS = ["MASTER_ID","SOURCE_ID","UWI","API_NUM","API_10","WELL_NAME","WELL_NUM",
        "OPERATOR_NAME","FIELD_NAME","SURFACE_LATITUDE","SURFACE_LONGITUDE",
        "BOTTOM_LATITUDE","BOTTOM_LONGITUDE","COUNTY","PROVINCE_STATE","COUNTRY",
        "LEGAL_SURVEY_TYPE","WELL_STATUS","WELL_TYPE","SPUD_DATE","COMPLETION_DATE",
        "PLUG_DATE","FINAL_TD","TVD","GROUND_ELEVATION","KB_ELEVATION",
        "PRODUCING_FORMATION","AREA","SOURCE_COUNT","SOURCE_LIST","MATCH_PASS",
        "MATCH_CONFIDENCE","CREATED_DATE"]
N = len(COLS)
TS = "CURRENT_TIMESTAMP()"

import os, json

def _build_boem_county():
    """Build the BOEM area-code -> name CASE from area_codes.json (all 85
    protraction areas, emitted by build_protraction_geojson.py). Falls back to
    the original 16-entry hardcoded map if the lookup file isn't present, so the
    view still builds on a machine that hasn't run the converter."""
    _lk = os.path.join(os.path.dirname(os.path.abspath(__file__)), "area_codes.json")
    _fallback = {
        "WC":"West Cameron","EC":"East Cameron","VR":"Vermilion",
        "SM":"South Marsh Island","EI":"Eugene Island","SS":"Ship Shoal",
        "ST":"South Timbalier","GB":"Garden Banks","GC":"Green Canyon",
        "MC":"Mississippi Canyon","EW":"Ewing Bank","KC":"Keathley Canyon",
        "WR":"Walker Ridge","AC":"Alaminos Canyon","EB":"East Breaks","HI":"High Island",
    }
    if os.path.exists(_lk):
        with open(_lk, encoding="utf-8") as _f:
            _m = json.load(_f)
    else:
        _m = _fallback
    # Emit a SQL CASE; escape single quotes in names.
    _whens = "\n            ".join(
        f"WHEN '{_c}' THEN '{_n.replace(chr(39), chr(39)*2)}'"
        for _c, _n in sorted(_m.items()))
    return "CASE BOTTOM_AREA_CODE\n            " + _whens + "\n            ELSE BOTTOM_AREA_CODE END"

BOEM_COUNTY = _build_boem_county()

sources = []

# ── Wells excluded from the federation (bad coordinates, confirmed by user) ──
# These stay in the RAW verbatim tables but are filtered out of the view.
EXCLUDED_WELLS = {
    "PA_DEP": ["194656"],
    "AK_AOGCC": ["50629218970000"],
    "IN_IGWS": ["180970"],
    "CO_BIP": ["4140", "21018"],
}

# ── TX: hand-coded with JOIN to completion table for OIL_GAS_CODE.
#    BOEM: hand-coded with protraction area decoder. ──

sources.append(("RAW_TX_DAF804",
    "TRY_CAST(w.GEOM_LATITUDE AS FLOAT) IS NOT NULL AND TRY_CAST(w.GEOM_LONGITUDE AS FLOAT) IS NOT NULL"
    " AND NOT (ABS(TRY_CAST(w.GEOM_LATITUDE AS FLOAT)) < 1 AND ABS(TRY_CAST(w.GEOM_LONGITUDE AS FLOAT)) < 1)", [
    "'TX_'||w.UWI", "'TX_RRC'", "w.UWI", "w.API_DISPLAY", "LEFT(w.UWI,10)", "w.LEASE_NAME", "w.WELL_NUMBER",
    "NULL",
    "NULL",
    "TRY_CAST(w.GEOM_LATITUDE AS FLOAT)", "TRY_CAST(w.GEOM_LONGITUDE AS FLOAT)",
    "NULL", "NULL",
    "INITCAP(w.COUNTY_NAME)", "'TX'", "'US'", "'ABSTRACT'",
    "w.WELL_STATUS_DESC",
    "CASE c.\"OIL_GAS_CODE\" WHEN 'O' THEN 'OIL' WHEN 'G' THEN 'GAS' ELSE w.TYPE_APPLICATION_DESC END",
    "w.SPUD_DATE", "NULL",
    "NULL",
    "w.TOTAL_DEPTH", "NULL", "NULL", "NULL",
    "NULL",
    "w.DISTRICT",
    "1", "'TX_RRC'", "1", "1.0", TS],
    "RAW_TX_DAF804.WELL w LEFT JOIN RAW_TX_COMPLETION.WELL_COMPLETION c ON LEFT(w.UWI,10) = c.\"API_10\""))

# ---- BOEM: offshore GOM. Old pre-mapped canonical columns (not yet verbatim-reloaded).
#         BOTTOM_AREA_CODE decoded to full protraction area names for the dropdown. ----
_BOEM_AREAS = {
    "AC":"Acwater Valley","AM":"Alaminos Canyon","AT":"Atwater Valley",
    "BA":"Brazos Area","BM":"Bryan Mound","BN":"Bienville",
    "CA":"Chandeleur Area","CG":"Cognac","CH":"Chandeleur Sound",
    "CI":"Clipper Island","DC":"DeSoto Canyon","EB":"East Breaks",
    "EI":"Eugene Island","EW":"Ewing Bank","FP":"Florida Plain",
    "GA":"Galveston Area","GB":"Garden Banks","GC":"Green Canyon",
    "GI":"Grand Isle","GM":"Gainesville","GP":"Galveston Block Protraction",
    "GR":"Gloria","GV":"Galveston","HE":"Henderson","HI":"High Island",
    "HP":"High Island Block Protraction","KC":"Keathley Canyon",
    "KW":"Key West","LB":"Lloyd Block","LL":"Lloyd Ridge",
    "LU":"Lund","MA":"Matagorda Island","MC":"Mississippi Canyon",
    "MI":"Mustang Island Area","MO":"Mobile Area","MP":"Main Pass",
    "MS":"Mobile South","MU":"Mustang Island","PE":"Pelican Island",
    "PI":"Port Isabel","PL":"Placid","PN":"Pensacola",
    "PR":"Perdido","PS":"Pulley Ridge South","RA":"Rio Grande",
    "SA":"South Addition","SB":"Sabine Pass","SH":"South Pelto",
    "SM":"South Marsh Island","SP":"South Pass","SS":"Ship Shoal",
    "ST":"South Timbalier","TA":"Tarpon Springs","TS":"Texas State",
    "VK":"Viosca Knoll","VR":"Vermilion","WC":"West Cameron",
    "WD":"West Delta","WR":"Walker Ridge",
}
_BOEM_CASE = "CASE BOTTOM_AREA_CODE " + " ".join(
    f"WHEN '{k}' THEN '{v}'" for k, v in _BOEM_AREAS.items()
) + " ELSE BOTTOM_AREA_CODE END"

sources.append(("RAW_BOEM",
    "SURFACE_LATITUDE IS NOT NULL AND SURFACE_LONGITUDE IS NOT NULL"
    " AND NOT (ABS(SURFACE_LATITUDE) < 1 AND ABS(SURFACE_LONGITUDE) < 1)", [
    "'GOM_'||WELL_ID", "'GOM_BOEM'", "API_WELL_NUMBER", "API_WELL_NUMBER",
    "LEFT(API_WELL_NUMBER,10)", "WELL_NAME", "NULL",
    "COMPANY_NAME", "NULL",
    "SURFACE_LATITUDE", "SURFACE_LONGITUDE",
    "TRY_CAST(NULLIF(BOTTOM_LATITUDE,'') AS FLOAT)", "TRY_CAST(NULLIF(BOTTOM_LONGITUDE,'') AS FLOAT)",
    _BOEM_CASE, "'GOM'", "'US'", "'OCS'",
    "STATUS_CODE", "TYPE_CODE", "SPUD_DATE", "NULL",
    "NULL", "CAST(NULLIF(BH_TOTAL_MD_FT,'') AS VARCHAR)",
    "TRY_CAST(NULLIF(TRUE_VERTICAL_DEPTH_FT,'') AS FLOAT)", "NULL", "NULL",
    "NULL", "REGION",
    "1", "'GOM_BOEM'", "1", "1.0", TS]))

# ---- Auto-branches: every source the Federation Loader has pushed is recorded
#         in federation_sources.json. Those tables hold CANONICAL columns (the
#         loader runs apply_mapping before pushing), so one template fits them
#         all. Hand-coded sources above take precedence; we skip any source_id
#         already emitted so nothing doubles up. This is what lets a new country
#         federate with no edit to this file. ----
import json, os


def _canonical_branch(_sid, _s):
    """Original auto-branch: assumes the loader pre-mapped to canonical columns
    (the legacy normalize-at-load path). Used for any registered source that has
    NO stored 'mapping' (e.g. sources loaded before the verbatim refactor)."""
    _prefix = _s["prefix"]
    _legal = f"'{_s['legal']}'" if _s.get("legal") else "NULL"
    _api10 = "LEFT(API_14,10)" if _s.get("std_uwi") else "NULL"
    return ("RAW_" + _prefix if not _s["schema"].startswith("RAW_") else _s["schema"],
        "TRY_CAST(SURFACE_LATITUDE AS FLOAT) IS NOT NULL AND TRY_CAST(SURFACE_LONGITUDE AS FLOAT) IS NOT NULL"
        " AND NOT (ABS(TRY_CAST(SURFACE_LATITUDE AS FLOAT)) < 1 AND ABS(TRY_CAST(SURFACE_LONGITUDE AS FLOAT)) < 1)", [
        f"'{_prefix}_'||UWI", f"'{_sid}'", "UWI", "API_NUM", _api10, "WELL_NAME", "WELL_NUM",
        "OPERATOR_NAME", "FIELD_NAME", "TRY_CAST(SURFACE_LATITUDE AS FLOAT)", "TRY_CAST(SURFACE_LONGITUDE AS FLOAT)",
        "TRY_CAST(BOTTOM_LATITUDE AS FLOAT)", "TRY_CAST(BOTTOM_LONGITUDE AS FLOAT)",
        "COUNTY", "PROVINCE_STATE", f"'{_s.get('country','US')}'", _legal, "WELL_STATUS", "WELL_TYPE",
        "SPUD_DATE", "COMPLETION_DATE", "PLUG_DATE", "FINAL_TD", "TVD", "GROUND_ELEVATION",
        "KB_ELEVATION", "PRODUCING_FORMATION", "AREA", "1", f"'{_sid}'", "1", "1.0", TS])


def _mapped_branch(_sid, _s):
    """Verbatim-raw auto-branch: the loader pushed the source's ORIGINAL columns
    untouched, so we map them HERE from the saved per-source mapping
    ({TARGET_FIELD: source_column}). The loader also appends two derived columns
    the SQL can't easily build itself: _FED_API_14 (the standardized match key)
    and _FED_COUNTY (county code already resolved to a name). Source identifiers
    are double-quoted to preserve original case/spacing."""
    _mapping = _s["mapping"]
    _prefix = _s["prefix"]
    _legal = f"'{_s['legal']}'" if _s.get("legal") else "NULL"
    _pstate = (_s.get("province_state") or "").strip()

    def _q(c):                       # quote an identifier, escaping embedded quotes
        return '"' + str(c).replace('"', '""') + '"'

    def _col(field):                 # mapped source column, or NULL
        c = _mapping.get(field)
        return _q(c) if c else "NULL"

    def _fcol(field):                # mapped source column, cast to FLOAT, or NULL
        c = _mapping.get(field)
        return f"TRY_CAST({_q(c)} AS FLOAT)" if c else "NULL"

    _uwi = _col("UWI")
    _master = f"'{_prefix}_'||{_uwi}" if _uwi != "NULL" else f"'{_prefix}_'||{_col('API_NUM')}"
    _api10 = f'LEFT({_q("_FED_API_14")},10)' if _s.get("std_uwi") else "NULL"
    # province_state: fixed code if the loader stored one, else the mapped column.
    if _pstate:
        _province = f"'{_pstate}'"
    else:
        _province = _col("PROVINCE_STATE")
    # coords gate the branch, same as everywhere else.
    _lat, _lon = _mapping.get("SURFACE_LATITUDE"), _mapping.get("SURFACE_LONGITUDE")
    _where = (f"TRY_CAST({_q(_lat)} AS FLOAT) IS NOT NULL AND TRY_CAST({_q(_lon)} AS FLOAT) IS NOT NULL"
              f" AND NOT (ABS(TRY_CAST({_q(_lat)} AS FLOAT)) < 1 AND ABS(TRY_CAST({_q(_lon)} AS FLOAT)) < 1)"
              if _lat and _lon else "1=1")

    # county: prefer the Loader-resolved _FED_COUNTY, fall back to mapped COUNTY column
    _county_col = _col("COUNTY")
    if _county_col != "NULL":
        _county_expr = f'COALESCE({_q("_FED_COUNTY")}, {_county_col})'
    else:
        _county_expr = _q("_FED_COUNTY")

    return (_s["schema"], _where, [
        _master, f"'{_sid}'", _uwi, _col("API_NUM"), _api10, _col("WELL_NAME"), _col("WELL_NUM"),
        _col("OPERATOR_NAME"), _col("FIELD_NAME"), _fcol("SURFACE_LATITUDE"), _fcol("SURFACE_LONGITUDE"),
        _fcol("BOTTOM_LATITUDE"), _fcol("BOTTOM_LONGITUDE"),
        _county_expr, _province, f"'{_s.get('country','US')}'", _legal, _col("WELL_STATUS"), _col("WELL_TYPE"),
        _col("SPUD_DATE"), _col("COMPLETION_DATE"), _col("PLUG_DATE"), _col("FINAL_TD"), _fcol("TVD"), _fcol("GROUND_ELEVATION"),
        _fcol("KB_ELEVATION"), _col("PRODUCING_FORMATION"), _col("AREA"), "1", f"'{_sid}'", "1", "1.0", TS])


_emitted = {item[2][1].strip("'") for item in sources}  # SOURCE_ID literals
_store_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "federation_sources.json")
if os.path.exists(_store_path):
    with open(_store_path, encoding="utf-8") as _f:
        _store = json.load(_f)
    for _sid, _s in sorted(_store.items()):
        if _sid in _emitted:
            continue  # a hand-coded branch already covers this source
        # Verbatim sources carry a saved 'mapping'; legacy canonical ones don't.
        if _s.get("mapping"):
            sources.append(_mapped_branch(_sid, _s))
        else:
            sources.append(_canonical_branch(_sid, _s))
        _emitted.add(_sid)

# validate + emit
for item in sources:
    schema, where, exprs = item[0], item[1], item[2]
    assert len(exprs) == N, f"{schema}: {len(exprs)} != {N}"

header = "CREATE OR REPLACE VIEW WELL_FEDERATION.CURATED.V_WELL_FEDERATION(\n\t" + ",\n\t".join(COLS) + "\n) AS\n"
blocks = []
for item in sources:
    schema, where, exprs = item[0], item[1], item[2]
    from_clause = item[3] if len(item) > 3 else f"{schema}.WELL"
    # Check if this source has excluded wells (bad coordinates)
    _src_id = exprs[1].strip("'")
    _excl = EXCLUDED_WELLS.get(_src_id)
    _excl_sql = ""
    if _excl:
        _vals = ",".join(f"'{v}'" for v in _excl)
        _uwi_expr = exprs[2]
        _excl_sql = f" AND {_uwi_expr} NOT IN ({_vals})"
    sel = "SELECT " + ", ".join(exprs) + f"\nFROM {from_clause} WHERE {where}{_excl_sql}"
    blocks.append(sel)
sql = header + "\nUNION ALL\n".join(blocks) + ";\n"
open("v_well_federation_widened.sql","w").write(sql)
print(f"{len(sources)} branches, {N} columns each — all aligned")
print("bytes:", len(sql))
