r"""
refactor_to_package.py (v4) — turn the flat repo into a `dataview` package whose folders mirror
the app's nav cards. Rewrites ALL imports to real package paths (no sys.path hacks, so
subprocesses work).

v3 changes (plan/apply mechanics — DOMAINS rules unchanged from v2):
  * COLLISION-SAFE: when a root file and a modules/ shim map to the same destination
    (the Tier-1 `from X import *` re-exports), keep the ROOT file and QUARANTINE the
    shim into _refactor_quarantine/ — never clobber, never crash on Windows.
  * NO SILENT DROPS: .py files in other subfolders are reported as IGNORED, not dropped.
  * LANDMINE CHECK: flags files that are imported somewhere but stay unclassified in root
    (those break once importers move into the package).
  * DISCOVERY COUNT + post-apply leftover-import scan.

STRUCTURE (mirrors splash cards):
  dataview/core/            config, db, connect, schema, themes, fk, dialect
  dataview/mapping/         well map, spatial layers, h3, scout, shapefile
  dataview/import_data/     8-stage pipeline, staging->promote, importer, seeder, export
  dataview/db_explorer/     query/browse/export, schema overview
  dataview/file_catalog/    scan/enrich/extract/load, workers, vault, triage, docs, pdf
  dataview/reference_tables/ seed dv_r_*, lookups, standards manager
  dataview/region_builder/  region builder, petroleum regions
  tools/                    standalone scripts (NOT imported)

  py refactor_to_package.py            # DRY RUN — full plan + all flag lists
  py refactor_to_package.py --apply
"""
import os, re, ast, sys, shutil

APPLY = "--apply" in sys.argv
ROOT  = os.getcwd()
PKG   = "dataview"
QUAR  = "_refactor_quarantine"

DOMAINS = [
    ("core", [
        r"^config", r"^db\.py$", r"^db_dialect", r"^db_pool", r"^connect", r"^connection",
        r"^schema", r"^theme", r"^fk_catalog$", r"^fk$", r"^fk\.py", r"^fk_entity",
        r"^fk_resolve", r"^fk_resolution", r"^dialect", r"^_detect_dialect", r"^catalog_dialect",
        r"^base\.py$", r"^reset_demo", r"^demo_reset", r"^list_layers", r"^load_schema",
        r"^schema_introspect", r"^dw_utils", r"^ui_helpers", r"^licence", r"^page_licence",
        r"^delete_util", r"^validate$", r"^validate\.py", r"^bcp_transport", r"^path_identity",
        r"^hash_keys", r"^fingerprint", r"^ppdm_agent",
    ]),
    ("region_builder", [
        r"^page_region", r"^region_builder", r"^petroleum_region", r"^state_regions",
        r"^migrate_state_region", r"^migrate_petroleum_region",
    ]),
    ("mapping", [
        r"^page_well_map$", r"^page_well_map\.py$", r"^page_well_map_docs", r"^page_wl_map",
        r"^geography_layers",
        r"^h3_grids", r"^h3_map_layer", r"^run_h3", r"^shapefile", r"^build_county",
        r"^grids\.py$", r"^project_map", r"^protraction", r"^spatial_seeder", r"^map_layer",
        r"^federation_map", r"^mapping_studio", r"^page_mapping_studio", r"^page_ppdm_map",
        r"^populate_h3", r"^dv_spatial_loader", r"^shp_to_protraction",
        r"^populate_dv_well_protraction", r"^build_geojson", r"^refresh_demo_grids",
        r"^boem_geo", r"^us_geo",
    ]),
    ("db_explorer", [
        r"^page_db_explorer", r"^page_schema_overview", r"^page_data_model",
        r"^page_federation_search",
    ]),
    ("import_data", [
        r"^page_pipeline$", r"^page_pipeline\.py", r"^page_dv_importer", r"^page_dv_export",
        r"^pipeline_", r"^entity_seeder", r"^entity_map_seed", r"^run_stage", r"^run_promote",
        r"^importer", r"^column_mapper", r"^page_import", r"^page_bulk", r"^page_ai_importer",
        r"^page_fed_loader", r"^page_pipeline_tools", r"^page_run$", r"^exporters", r"^export_",
        r"^upload_to_snowflake", r"^staging", r"^promote$", r"^promote\.py", r"^normalize",
        r"^gom_well_loader", r"^repromote", r"^run_load$", r"^mapping\.py$",
    ]),
    ("reference_tables", [
        r"^page_standards_manager", r"^page_reference", r"^rtm", r"^standards",
        r"^reference_manager", r"^page_rules", r"^page_seed", r"^ref_seeder",
        r"^value_standardize", r"^user_rules", r"^standardize_well_attrs", r"^dv_standards_seed",
        r"^boem_area_codes", r"^boem_status_codes",
    ]),
    ("file_catalog", [
        r"^page_file", r"^page_workbench", r"^page_extraction_inspector", r"^page_monitor",
        r"^page_triage", r"^page_catalog_search", r"^page_dv_catalog", r"^page_vault",
        r"^page_pdf_catalog", r"^page_selected_documents", r"^page_well_documents",
        r"^worker_", r"^catalog_capture", r"^catalog_rules", r"^catalog_readiness",
        r"^catalog_scorecard", r"^catalog_docs", r"^bcp_capture", r"^promote_", r"^triage_",
        r"^pdf_survey", r"^pdf_db", r"^survey_loader", r"^vault_", r"^scout", r"^file_viewer",
        r"^doc_", r"^csv_catalog", r"^dlis_catalog", r"^segy_catalog", r"^lis_catalog",
        r"^p190_catalog", r"^witsml_catalog", r"^json_well_log_catalog", r"^dv_catalog_adapter",
        r"^file_header", r"^file_inventory", r"^file_summarizer", r"^current_run_scorecard",
        r"^seis_filename_parser", r"^format_library", r"^format_detective", r"^inv_auth",
        r"^inv_email", r"^inv_workbench", r"^enrich_file", r"^enrich_from", r"^ensure_catalog",
        r"^segy_header", r"^add_segy", r"^build_catalog_mirror", r"^work_queue",
        r"^dv_office_loader", r"^gom_dir_srvy_loader", r"^resolve_log_identity",
        r"^force_capture", r"^merge_bcp_capture", r"^collect_final_documents",
        r"^page_las", r"^page_shapefile_catalog", r"^run\.py$",
    ]),
]
TOOLS_HINT = [r"^bench", r"^profile_", r"^analyz", r"^cleanup", r"^diag", r"^check_",
              r"^verify_", r"^clone_", r"^clear_", r"^kill_", r"^gen_", r"^make_",
              r"^generat", r"^migrat", r"^trace_", r"^copy_", r"^setup_", r"^deploy",
              r"^probe", r"^recatalog", r"^recaptur", r"^audit", r"^breakdown", r"^dedup",
              r"^defrag", r"^test_", r"^show_", r"^dump_", r"^inspect", r"^find_", r"^count_",
              r"^fix_", r"^delete_", r"^ks_", r"^gold_", r"^poc_", r"^prep_", r"^reconcile",
              r"^recover", r"^rebuild", r"^diff_", r"^debug_", r"^compare_", r"^dev_resume",
              r"^tidy_", r"^who_", r"^slow_", r"^skip_", r"^gap$", r"^index_", r"^missing_",
              r"^organize_", r"^parallel_", r"^provenance", r"^repair_", r"^run_fixture",
              r"^finish_", r"^extract_", r"^dv_table_loader", r"^classify_dir", r"^docs_per_well",
              r"^build_well_master_gold", r"^cleaning", r"^bcp_probe"]
LOADER_HINT = [r"^load_", r"^seed_", r"^ingest_", r"^las_", r"^kgs", r"^walk_", r"^bulk_"]

PROTECT   = {"app_v3.py", "app_v4.py", "refactor_to_package.py"}
SKIP_DIRS = {"venv",".venv",".git","__pycache__","download",".vs","geojson","spatial",
             "schema_registry","output","assets","documentation","backup","_scratch",
             "seed_catalog", QUAR}
# dirs that are refactor OUTPUT — never gather FROM them (so re-runs are idempotent)
OUTPUT_DIRS = {PKG, "tools"}

def _top(rel): return rel.split(os.sep)[0]
def skipdir(dp):
    parts = os.path.relpath(dp, ROOT).split(os.sep)
    return bool(parts) and (parts[0] in SKIP_DIRS or parts[0].startswith(("_dead","_trash","_archive")))

def classify(basename):
    for dom, rules in DOMAINS:
        for rx in rules:
            if re.search(rx, basename, re.I): return (PKG, dom)
    for rx in LOADER_HINT:
        if re.search(rx, basename, re.I): return ("tools", None)
    for rx in TOOLS_HINT:
        if re.search(rx, basename, re.I): return ("tools", None)
    return None

# ── gather ─────────────────────────────────────────────────────────────────────
movable, ignored = [], []          # movable: root + modules/ ; ignored: other subfolders
for dp,dns,fns in os.walk(ROOT):
    if skipdir(dp): dns[:]=[]; continue
    dns[:]=[d for d in dns if d not in SKIP_DIRS and not d.startswith(("_dead","_trash","_archive"))]
    for fn in fns:
        if not fn.endswith(".py") or fn in PROTECT: continue
        rel = os.path.relpath(os.path.join(dp,fn), ROOT)
        top = _top(rel)
        if os.sep not in rel or top == "modules":
            movable.append(rel)
        elif top in OUTPUT_DIRS:
            continue                # already-refactored output; ignore on re-run
        else:
            ignored.append(rel)     # stray subfolder — REPORT, don't drop

# ── plan (destination per movable) ─────────────────────────────────────────────
cand = {}                          # rel -> (dest_relpath, imp_or_None)
unclassified = []
for rel in sorted(movable):
    d = classify(os.path.basename(rel))
    if d is None:
        unclassified.append(rel); continue
    pkg,dom = d
    stem = os.path.basename(rel)[:-3]
    if pkg == "tools":
        cand[rel] = (os.path.join("tools", os.path.basename(rel)), None)
    else:
        cand[rel] = (os.path.join(PKG, dom, os.path.basename(rel)), f"{PKG}.{dom}.{stem}")

# ── collision resolution: same dest -> keep root file, quarantine modules/ shim ──
by_dest = {}
for rel,(dest,imp) in cand.items():
    by_dest.setdefault(dest, []).append(rel)

plan, quarantine, conflict = {}, [], []
for dest, srcs in by_dest.items():
    if len(srcs) == 1:
        plan[srcs[0]] = cand[srcs[0]]; continue
    roots = [s for s in srcs if os.sep not in s]
    if len(roots) == 1:                     # clear winner: the root file
        plan[roots[0]] = cand[roots[0]]
        quarantine += [s for s in srcs if s != roots[0]]
    else:                                   # 0 or >1 root candidates -> don't guess
        conflict.append((dest, sorted(srcs)))

rename = {os.path.basename(o)[:-3]: imp for o,(n,imp) in plan.items() if imp}

# ── pre-existing destination guard: a dest file already on disk (e.g. a tracked
#    tools/ file) that is NOT itself being moved -> skip, never clobber/crash ──────
preexist = []
for src in list(plan.keys()):
    dest, _ = plan[src]
    dp = os.path.join(ROOT, dest)
    if os.path.exists(dp) and os.path.abspath(dp) != os.path.abspath(os.path.join(ROOT, src)):
        preexist.append((src, dest)); del plan[src]
rename = {os.path.basename(o)[:-3]: imp for o,(n,imp) in plan.items() if imp}

# ── landmine check: imported somewhere but staying unclassified/ignored ─────────
def _imported_stems():
    pat = re.compile(r"(?m)^\s*(?:import\s+([A-Za-z_]\w*)|from\s+(?:modules\.)?([A-Za-z_]\w*)\s+import)")
    seen = set()
    for dp,dns,fns in os.walk(ROOT):
        if skipdir(dp): dns[:]=[]; continue
        dns[:]=[d for d in dns if d not in SKIP_DIRS and not d.startswith(("_dead","_trash","_archive"))]
        for fn in fns:
            if not fn.endswith(".py"): continue
            try: txt = open(os.path.join(dp,fn),encoding="utf-8",errors="replace").read()
            except OSError: continue
            for m in pat.finditer(txt):
                seen.add(m.group(1) or m.group(2))
    return seen
imported = _imported_stems()
stray_stems = {os.path.basename(r)[:-3] for r in unclassified+ignored}
landmines = sorted(s for s in stray_stems if s in imported)

# ── report ──────────────────────────────────────────────────────────────────────
print(f"{'APPLY' if APPLY else 'DRY RUN'} — refactor to `{PKG}` package")
print(f"discovery: {len(movable)} movable (root + modules/), "
      f"{len(ignored)} in other subfolders, {len(unclassified)} unclassified\n")

bydom = {}
for old,(new,imp) in plan.items():
    bydom.setdefault(os.path.dirname(new),[]).append(os.path.basename(old))
for dom in sorted(bydom):
    print(f"  {dom}/  ({len(bydom[dom])})")
    for f in sorted(bydom[dom]): print(f"       {f}")
    print()

def _list(title, items):
    print(f"{title} ({len(items)}):")
    for x in items: print(f"   {x}")
    print()

_list(f"QUARANTINE — modules/ shim, root kept, moved to {QUAR}/", sorted(quarantine))
if conflict:
    print(f"CONFLICT — same destination, NO clear root winner, LEFT IN PLACE ({len(conflict)}):")
    for dest,srcs in sorted(conflict):
        print(f"   {dest}  <-  {', '.join(srcs)}")
    print()
_list("IGNORED — .py in other subfolders, NOT touched", sorted(ignored))
if preexist:
    print(f"** PRE-EXISTING — destination already on disk, SKIPPED to avoid clobber ({len(preexist)}):")
    for src,dest in sorted(preexist):
        print(f"     {src}  ->  {dest}  (already exists — reconcile by hand)")
    print()
_list("UNCLASSIFIED — staying in root", sorted(unclassified))
if landmines:
    print(f"** LANDMINES — imported somewhere but NOT classified ({len(landmines)}):")
    print("   these will break once their importers move into the package — classify them:")
    for s in landmines: print(f"     {s}")
    print()

print(f"total to move: {len(plan)}   quarantine: {len(quarantine)}   "
      f"conflict: {len(conflict)}   imports to rewrite: {len(rename)}")

if not APPLY:
    print("\n(DRY RUN) nothing changed. Review QUARANTINE / CONFLICT / IGNORED / UNCLASSIFIED /")
    print("LANDMINES above. Tell me any file->folder corrections and I'll adjust the rules.")
    sys.exit()

# ── apply ────────────────────────────────────────────────────────────────────────
for old,(new,imp) in plan.items():
    nd = os.path.join(ROOT, os.path.dirname(new)); os.makedirs(nd, exist_ok=True)
    if os.path.dirname(new).startswith(PKG):
        ii = os.path.join(nd,"__init__.py")
        if not os.path.exists(ii): open(ii,"w").close()
    shutil.move(os.path.join(ROOT,old), os.path.join(ROOT,new))
open(os.path.join(ROOT,PKG,"__init__.py"),"a").close()

for rel in quarantine:                       # preserve relative path under quarantine
    dst = os.path.join(ROOT, QUAR, rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(os.path.join(ROOT,rel), dst)

def rewrite(src):
    out = src
    for name,imp in rename.items():
        pp,mod = imp.rsplit(".",1)
        out = re.sub(rf"(?m)^(\s*)import {re.escape(name)}\b(?!\.)", rf"\1from {pp} import {mod}", out)
        out = re.sub(rf"(?m)^(\s*)from {re.escape(name)} import",   rf"\1from {imp} import", out)
        out = re.sub(rf"(?m)^(\s*)from modules\.{re.escape(name)} import", rf"\1from {imp} import", out)
        out = re.sub(rf"(?m)^(\s*)import modules\.{re.escape(name)}\b",     rf"\1from {pp} import {mod}", out)
    return out

changed = 0
for dp,dns,fns in os.walk(ROOT):
    if skipdir(dp): dns[:]=[]; continue
    dns[:]=[d for d in dns if d not in SKIP_DIRS and not d.startswith(("_dead","_trash","_archive"))]
    for fn in fns:
        if not fn.endswith(".py"): continue
        p = os.path.join(dp,fn); src = open(p,encoding="utf-8",errors="replace").read()
        new = rewrite(src)
        if new != src:
            try: ast.parse(new)
            except SyntaxError as e:
                print(f"  WARN broke {os.path.relpath(p,ROOT)}: {e}; left as-is"); continue
            open(p,"w",encoding="utf-8").write(new); changed += 1

# ── post-apply leftover-import scan (things the line-based rewrite can't catch) ──
leftovers = []
moved_stems = set(rename)
for dp,dns,fns in os.walk(ROOT):
    if skipdir(dp): dns[:]=[]; continue
    dns[:]=[d for d in dns if d not in SKIP_DIRS and not d.startswith(("_dead","_trash","_archive"))]
    for fn in fns:
        if not fn.endswith(".py"): continue
        p = os.path.join(dp,fn); txt = open(p,encoding="utf-8",errors="replace").read()
        rp = os.path.relpath(p,ROOT)
        if re.search(r"(?m)^\s*(?:from|import)\s+modules\.", txt):
            leftovers.append(f"{rp}: residual `modules.` import")
        for s in moved_stems:
            if (re.search(rf"^\s*import\s+[\w ]+,\s*{s}\b", txt, re.M) or
                    re.search(rf"^\s*import\s+{s}\s*,", txt, re.M)):
                leftovers.append(f"{rp}: comma-import of moved `{s}` (rewrite skipped it)")
            if re.search(rf"\bmodules\.{s}\.", txt):
                leftovers.append(f"{rp}: attribute use `modules.{s}.` (rewrite the usage by hand)")

print(f"\nAPPLIED. moved {len(plan)}, quarantined {len(quarantine)}, rewrote imports in {changed} files.")
if leftovers:
    print(f"\n** {len(leftovers)} leftover import(s) to fix by hand:")
    for x in leftovers: print(f"   {x}")
print("RESTART Streamlit, click every page, RUN THE PIPELINE.")
