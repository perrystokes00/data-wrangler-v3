r"""
refactor_to_package.py — turn the flat repo into a proper `dataview` package whose folders
mirror the app's navigation cards. Rewrites ALL imports to real package paths (no sys.path
hacks). Subprocesses work because it's a real installed-style package run from root.

STRUCTURE (mirrors the splash cards):
  dataview/core/              shared: config, db, connection, schema, themes, fk
  dataview/mapping/           Mapping card: well map, spatial layers, h3, scout, region
  dataview/import_data/       Import Data card: 8-stage pipeline, staging->promote
  dataview/db_explorer/       DB Explorer card: query/browse/export
  dataview/file_catalog/      File Catalog card: scan/enrich/extract/load, workers, vault
  dataview/reference_tables/  Reference Tables card: seed dv_r_*, lookups, standards
  dataview/region_builder/    Region Builder card
  tools/                      standalone scripts (NOT imported): benchmarks, one-offs

USAGE:
  py refactor_to_package.py            # DRY RUN — full plan, changes nothing
  py refactor_to_package.py --apply    # move files, rewrite imports, patch app_v3

The dry run prints: (a) each file's destination, (b) every import that will be rewritten.
REVIEW IT before --apply. Everything is git-tracked so it's revertible.
"""
import os, re, ast, sys, shutil

APPLY = "--apply" in sys.argv
ROOT = os.getcwd()
PKG = "dataview"

# ── domain rules (first match wins). Based on the app's nav cards. ──
DOMAINS = [
    ("core", [
        r"^config", r"^db\.py$", r"^db_", r"^connect", r"^connection", r"^schema",
        r"^themes?", r"^fk_catalog", r"^dialect", r"^_detect_dialect", r"^base\.py$",
        r"^reset_demo", r"^demo_reset", r"^list_layers", r"^load_schema",
    ]),
    ("mapping", [
        r"^page_well_map", r"^page_wl_map", r"^page_region_builder", r"^geography_layers",
        r"^h3", r"^run_h3", r"^shapefile", r"geojson", r"^build_county", r"^grids\.py$",
        r"^project_map", r"protraction", r"^spatial", r"^map_",
    ]),
    ("region_builder", [
        r"^region_builder", r"^page_region", r"petroleum_region", r"^migrate_.*region",
    ]),
    ("import_data", [
        r"^page_pipeline", r"^page_dv_importer", r"^pipeline_", r"^entity_seeder",
        r"^page_dv_export", r"^run_stage", r"^run_promote", r"^page_dv_export",
        r"^importer", r"^column_mapper", r"^format_detective",
    ]),
    ("db_explorer", [
        r"^page_db_explorer", r"^page_schema_overview",
    ]),
    ("file_catalog", [
        r"^page_file_catalog", r"^page_file_manager", r"^page_workbench",
        r"^page_extraction_inspector", r"^page_monitor", r"^page_triage",
        r"^worker_core", r"^catalog_", r"^bcp_capture", r"^promote_", r"^triage_",
        r"^pdf_survey", r"^survey_loader", r"^vault_", r"^scout", r"^curve_",
        r"^page_selected_documents", r"^page_well_documents", r"^file_viewer", r"^doc_",
    ]),
    ("reference_tables", [
        r"^page_standards_manager", r"^page_reference", r"^rtm", r"^reference_",
        r"^standards", r"^seed_ref", r"^seed_uom", r"^seed_political",
    ]),
]
# standalone scripts (not imported) -> tools/ (checked only if nothing above matches AND
# the file looks like a run-by-hand script)
TOOLS_HINT = [r"^bench", r"^profile_", r"^analyze_", r"^cleanup_", r"^diag", r"^check_",
              r"^verify_", r"^clone_", r"^clear_", r"^kill_", r"^gen_", r"^make_",
              r"^generate_", r"^migrate_", r"^validate_", r"^trace_", r"^walk_",
              r"^load_", r"^seed_", r"^ingest_", r"^las_", r"^kgs_", r"^copy_",
              r"^setup_", r"^deploy", r"^probe", r"^bulk_", r"^recatalog", r"^recapture"]

PROTECT = {"app_v3.py", "refactor_to_package.py"}
SKIP_DIRS = {"venv",".venv",".git","__pycache__","download",".vs","geojson","spatial",
             "schema_registry","output","assets","documentation","backup","_scratch",
             "seed_catalog"}
def skip(dp):
    parts=os.path.relpath(dp,ROOT).split(os.sep)
    return parts and (parts[0] in SKIP_DIRS or parts[0].startswith(("_dead","_trash","_archive")))

def classify(basename):
    for dom, rules in DOMAINS:
        for rx in rules:
            if re.search(rx, basename, re.I): return (PKG, dom)
    for rx in TOOLS_HINT:
        if re.search(rx, basename, re.I): return ("tools", None)
    return None  # unmatched -> stays in root (safe)

# gather all local module files (py) not in skip dirs
local_files = {}   # basename(no ext) -> current relpath
for dp,dns,fns in os.walk(ROOT):
    if skip(dp): dns[:]=[]; continue
    dns[:]=[d for d in dns if d not in SKIP_DIRS and not d.startswith(("_dead","_trash","_archive"))]
    for fn in fns:
        if fn.endswith(".py") and fn not in PROTECT:
            local_files[fn[:-3]] = os.path.relpath(os.path.join(dp,fn), ROOT)

# decide destination for each ROOT-level and modules/ file
plan = {}   # current_rel -> (new_rel, new_import_path or None)
for stem, rel in sorted(local_files.items()):
    # only reorganize files currently at root or in modules/
    top = rel.split(os.sep)[0]
    if top not in (".",) and os.sep in rel and top not in ("modules",):
        # already in some other subfolder (translators/, importer/, etc.) — leave for now
        continue
    dest = classify(os.path.basename(rel))
    if dest is None:
        continue  # stays where it is
    pkg, dom = dest
    if pkg == "tools":
        new_rel = os.path.join("tools", os.path.basename(rel))
        new_import = None  # tools aren't imported
    else:
        new_rel = os.path.join(PKG, dom, os.path.basename(rel))
        new_import = f"{PKG}.{dom}.{stem}"
    plan[rel] = (new_rel, new_import)

# build rename map: old module name -> new dotted import
rename = {os.path.basename(old)[:-3]: imp for old,(new,imp) in plan.items() if imp}

print(f"{'APPLY' if APPLY else 'DRY RUN'} — refactor to `{PKG}` package (folders mirror nav cards)\n")
bydom={}
for old,(new,imp) in sorted(plan.items()):
    bydom.setdefault(os.path.dirname(new), []).append((old,new))
for dom in sorted(bydom):
    print(f"  {dom}/  ({len(bydom[dom])} files)")
    for old,new in bydom[dom][:10]:
        print(f"       {os.path.basename(old)}")
    if len(bydom[dom])>10: print(f"       ... and {len(bydom[dom])-10} more")
    print()
print(f"total files to move: {len(plan)}")
print(f"module imports to rewrite: {len(rename)} distinct names\n")
print("Sample import rewrites:")
for name, imp in list(rename.items())[:8]:
    print(f"   import {name}          ->  from {imp.rsplit('.',1)[0]} import {name}")
    print(f"   from {name} import X    ->  from {imp} import X")

if not APPLY:
    print("\n(DRY RUN) nothing changed. Review the destinations + rewrites above.")
    print("Tell me to adjust any file's domain, or re-run with --apply.")
    sys.exit()

# ── APPLY ──
# 1) move files, create packages
for old,(new,imp) in plan.items():
    nd=os.path.join(ROOT,os.path.dirname(new)); os.makedirs(nd,exist_ok=True)
    initf=os.path.join(nd,"__init__.py")
    if os.path.dirname(new).startswith(PKG) and not os.path.exists(initf): open(initf,"w").close()
    shutil.move(os.path.join(ROOT,old), os.path.join(ROOT,new))
# ensure top package __init__
open(os.path.join(ROOT,PKG,"__init__.py"),"a").close()

# 2) rewrite imports in EVERY py file (root + package + modules refs)
def rewrite(src):
    out=src
    for name, imp in rename.items():
        pkgpath, mod = imp.rsplit(".",1)
        # `import name`  -> `from pkgpath import mod`
        out=re.sub(rf"(?m)^(\s*)import {re.escape(name)}\b(?!\.)",
                   rf"\1from {pkgpath} import {mod}", out)
        # `from name import X` -> `from imp import X`
        out=re.sub(rf"(?m)^(\s*)from {re.escape(name)} import",
                   rf"\1from {imp} import", out)
        # `from modules.name import X` -> `from imp import X`
        out=re.sub(rf"(?m)^(\s*)from modules\.{re.escape(name)} import",
                   rf"\1from {imp} import", out)
        # `import modules.name` -> `from pkgpath import mod`
        out=re.sub(rf"(?m)^(\s*)import modules\.{re.escape(name)}\b",
                   rf"\1from {pkgpath} import {mod}", out)
    return out

changed=0
for dp,dns,fns in os.walk(ROOT):
    if skip(dp): dns[:]=[]; continue
    dns[:]=[d for d in dns if d not in SKIP_DIRS and not d.startswith(("_dead","_trash","_archive"))]
    for fn in fns:
        if not fn.endswith(".py"): continue
        p=os.path.join(dp,fn)
        src=open(p,encoding="utf-8",errors="replace").read()
        new=rewrite(src)
        if new!=src:
            try: ast.parse(new)
            except SyntaxError as e:
                print(f"  WARN: rewrite broke {os.path.relpath(p,ROOT)} ({e}); left unchanged"); continue
            open(p,"w",encoding="utf-8").write(new); changed+=1

print(f"\nAPPLIED. moved {len(plan)} files, rewrote imports in {changed} files.")
print("RESTART Streamlit, click every page, RUN THE PIPELINE (subprocess test).")
print("If an import breaks: it names the module; tell me and we fix that file's domain/rewrite.")
