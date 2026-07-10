"""
patch_promote_gold_coords.py — fill cat_well surface coords from well_master_gold
BEFORE the promote coord-gate, so wells that gold has a location for promote
instead of being held. Previously gold enrichment ran only post-promote
(enrich_from_gold), so coordless wells were held and never enriched. Set-based,
matched on normalized UWI = gold.uwi14, fills only NULL/(0,0). In place, .bak.
Run: py patch_promote_gold_coords.py
"""
import sys, ast
P = "promote_catalog.py"
s = open(P, encoding="utf-8").read()
if "_fill_cat_coords_from_gold" in s:
    print("already patched"); sys.exit(0)

helper = '''def _fill_cat_coords_from_gold(cur, cat, lat_col, lon_col, uwi_filter, params):
    """Pre-gate coord enrichment: fill cat_well surface coords from
    well_master_gold (matched on normalized UWI = gold.uwi14) so a well gold
    has a location for promotes rather than being held by REQUIRE_WELL_COORDS.
    Fills only NULL/(0,0). Returns rows filled (0 on any error)."""
    gold = "WELL_REF.well_ref.well_master_gold"
    try:
        cur.execute(
            f"UPDATE m SET m.[{lat_col}] = g.surface_latitude, "
            f"m.[{lon_col}] = g.surface_longitude "
            f"FROM {CAT_SCHEMA}.{cat} m "
            f"JOIN {gold} g ON g.uwi14 = {_norm('m.UWI')} "
            f"WHERE m.PROMOTED = 0{uwi_filter} "
            f"AND (m.[{lat_col}] IS NULL OR m.[{lon_col}] IS NULL "
            f"OR (m.[{lat_col}] = 0 AND m.[{lon_col}] = 0)) "
            f"AND g.surface_latitude IS NOT NULL AND g.surface_longitude IS NOT NULL "
            f"AND NOT (g.surface_latitude = 0 AND g.surface_longitude = 0)", *params)
        return cur.rowcount or 0
    except Exception:
        return 0


'''
anchor_fn = "def _promote_header(cur, dv, cat, shared, uwi_filter, params, apply):\n"
if anchor_fn not in s:
    print("FAILED: _promote_header not found."); sys.exit(1)
s = s.replace(anchor_fn, helper + anchor_fn, 1)

# call it right after the coord gate is composed, before the eligible count
old = "    base = base + coord_pred\n"
new = ("    base = base + coord_pred\n"
       "    # PRE-GATE: give coordless wells a location from gold so they promote\n"
       "    # instead of being held (gold enrich used to run only post-promote).\n"
       "    if apply and REQUIRE_WELL_COORDS and _lat and _lon:\n"
       "        _fill_cat_coords_from_gold(cur, cat, _lat, _lon, uwi_filter, params)\n")
if old not in s:
    print("FAILED: 'base = base + coord_pred' anchor not found."); sys.exit(1)
s = s.replace(old, new, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: promote fills cat_well coords from gold before the coord-gate")
