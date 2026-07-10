r"""
patch_map_has_docs.py — add a 'Has documents' Query option to the mapping page.
The option must be added in SIX places that must agree, or it won't display and/or
won't execute:
  1. _QUERY_MAP (label->qtype for the early resolver)          [execution]
  2. the has_docs WHERE handler (EXISTS in GLOBAL_FILE_CATALOG) [execution]
  3. QUERIES dict (label->qtype for the dropdown)              [display]
  4. _query_labels ordered whitelist (visible ordering)        [display]
  5. area "queries" whitelists (wherever has_tops appears)     [display per area]
  6. the wells-load trigger + in-memory no-op filter lists     [behavior]
In place, .bak, idempotent. py patch_map_has_docs.py
"""
import sys, os, ast
P = "page_well_map.py"
if not os.path.exists(P):
    sys.exit("page_well_map.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()
n_before = s.count("has_docs")

def sub(old, new, s, label):
    if old not in s:
        print(f"  ! anchor MISSING for {label} — skipped")
        return s, False
    if new in s and old not in s:
        return s, False
    return s.replace(old, new, 1), True

changed = []

# 1) _QUERY_MAP (early resolver)
s, ok = sub(
    '''    _QUERY_MAP = {"By UWI":"uwi", "By source":"source", "By operator":"operator",
                  "By well type":"well_type", "By area":"area",
                  "Has formation tops":"has_tops", "Has production data":"has_prod",''',
    '''    _QUERY_MAP = {"By UWI":"uwi", "By source":"source", "By operator":"operator",
                  "By well type":"well_type", "By area":"area",
                  "Has documents":"has_docs",
                  "Has formation tops":"has_tops", "Has production data":"has_prod",''',
    s, "1:_QUERY_MAP")
changed.append(("_QUERY_MAP", ok))

# 2) WHERE handler (execution) — add has_docs before has_tops
s, ok = sub(
    '''    elif _early_qtype == "has_tops":
        _qry_where = "AND EXISTS (SELECT 1 FROM dataview.dv_well_formation_top t WHERE t.uwi = w.uwi)"''',
    '''    elif _early_qtype == "has_docs":
        _qry_where = ("AND EXISTS (SELECT 1 FROM file_catalog.GLOBAL_FILE_CATALOG g "
                      "WHERE g.UWI14 = w.uwi AND ISNULL(g.FLAG_DELETE,'N') <> 'Y')")
    elif _early_qtype == "has_tops":
        _qry_where = "AND EXISTS (SELECT 1 FROM dataview.dv_well_formation_top t WHERE t.uwi = w.uwi)"''',
    s, "2:WHERE handler")
changed.append(("WHERE_handler", ok))

# 3) QUERIES dict (dropdown labels)
s, ok = sub(
    '''        "Has formation tops":"has_tops","Has production data":"has_prod",
        "Has DST":"has_dst","Has directional survey":"has_survey",
        "Has core data":"has_core","Has core photos":"has_core_photos",
        "Has petro interpretation":"has_petro",
    }''',
    '''        "Has documents":"has_docs",
        "Has formation tops":"has_tops","Has production data":"has_prod",
        "Has DST":"has_dst","Has directional survey":"has_survey",
        "Has core data":"has_core","Has core photos":"has_core_photos",
        "Has petro interpretation":"has_petro",
    }''',
    s, "3:QUERIES dict")
changed.append(("QUERIES_dict", ok))

# 4) _query_labels ordered whitelist (visible ordering)
s, ok = sub(
    '''        ["all","uwi","operator","well_type","source","area",
         "td_range","spud_range","comp_range",
         "has_tops","has_prod","has_dst","has_survey",
         "has_core","has_core_photos","has_petro"]''',
    '''        ["all","uwi","operator","well_type","source","area",
         "td_range","spud_range","comp_range",
         "has_docs",
         "has_tops","has_prod","has_dst","has_survey",
         "has_core","has_core_photos","has_petro"]''',
    s, "4:_query_labels")
changed.append(("_query_labels", ok))

# 5) area "queries" whitelists — add has_docs wherever has_tops leads a queries list
#    (two known area blocks). Replace each occurrence of the has_tops-led fragment.
_area_old = '''                 "has_tops", "has_prod", "has_dst", "has_survey",'''
_area_new = '''                 "has_docs",
                 "has_tops", "has_prod", "has_dst", "has_survey",'''
_n5 = s.count(_area_old)
s = s.replace(_area_old, _area_new)
changed.append((f"area_queries(x{_n5})", _n5 > 0))

# 6a) wells-load trigger list
s, ok = sub(
    '''    if qtype in ("uwi", "operator", "well_type", "source", "area",
                 "td_range", "spud_range", "comp_range",
                 "has_tops", "has_prod", "has_dst",
                 "has_survey", "has_core", "has_core_photos", "has_petro"):''',
    '''    if qtype in ("uwi", "operator", "well_type", "source", "area",
                 "td_range", "spud_range", "comp_range", "has_docs",
                 "has_tops", "has_prod", "has_dst",
                 "has_survey", "has_core", "has_core_photos", "has_petro"):''',
    s, "6a:load-trigger")
changed.append(("load_trigger", ok))

# 6b) in-memory no-op filter list (SQL already pushed down)
s, ok = sub(
    '''            elif qtype in ("has_tops","has_prod","has_dst",
                           "has_survey","has_core","has_core_photos","has_petro"):''',
    '''            elif qtype in ("has_docs","has_tops","has_prod","has_dst",
                           "has_survey","has_core","has_core_photos","has_petro"):''',
    s, "6b:inmem-noop")
changed.append(("inmem_noop", ok))

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
n_after = s.count("has_docs")
print(f"patched {P}: has_docs occurrences {n_before} -> {n_after}")
for name, ok in changed:
    print(f"   {'OK ' if ok else '!! '} {name}")
